package main

// This file contains the read-only Google Cloud implementation of
// WebCloudCapabilityProber. It obtains Application Default Credentials through
// official Google clients and exposes no way to supply credential material.

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	artifactregistry "google.golang.org/api/artifactregistry/v1"
	bigquery "google.golang.org/api/bigquery/v2"
	cloudresourcemanager "google.golang.org/api/cloudresourcemanager/v1"
	"google.golang.org/api/googleapi"
	iam "google.golang.org/api/iam/v1"
	"google.golang.org/api/option"
	serviceusage "google.golang.org/api/serviceusage/v1"
	storage "google.golang.org/api/storage/v1"
)

const (
	webGoogleCloudReadOnlyScope = "https://www.googleapis.com/auth/cloud-platform.read-only"
	// IAM v1 exposes no read-only OAuth scope. This scope is used only by the
	// dedicated IAM client; the verifier's read-only IAM roles remain the
	// effective authorization boundary and the adapter exposes only Get.
	webGoogleCloudIAMScope = "https://www.googleapis.com/auth/cloud-platform"
)

const (
	webMissingServiceVertexAI         = "SERVICE_VERTEX_AI_DISABLED"
	webMissingServiceDataflow         = "SERVICE_DATAFLOW_DISABLED"
	webMissingServiceBigQuery         = "SERVICE_BIGQUERY_DISABLED"
	webMissingServiceArtifactRegistry = "SERVICE_ARTIFACT_REGISTRY_DISABLED"
	webMissingServiceIAM              = "SERVICE_IAM_DISABLED"
	webMissingServiceIAMCredentials   = "SERVICE_IAM_CREDENTIALS_DISABLED"
	webMissingServiceStorage          = "SERVICE_STORAGE_DISABLED"

	webMissingVerifierServiceUsageViewer = "VERIFIER_ROLE_SERVICE_USAGE_VIEWER_MISSING"
	webMissingVerifierSecurityReviewer   = "VERIFIER_ROLE_SECURITY_REVIEWER_MISSING"
	webMissingVerifierBigQueryMetadata   = "VERIFIER_ROLE_BIGQUERY_METADATA_VIEWER_MISSING"
	webMissingVerifierArtifactReader     = "VERIFIER_ROLE_ARTIFACT_READER_MISSING"
	webMissingVerifierStorageViewer      = "VERIFIER_ROLE_STORAGE_VIEWER_MISSING"

	webMissingWorkerAccount            = "WORKER_SERVICE_ACCOUNT_MISSING"
	webMissingWorkerDataflowWorker     = "WORKER_ROLE_DATAFLOW_WORKER_MISSING"
	webMissingWorkerDataflowDeveloper  = "WORKER_ROLE_DATAFLOW_DEVELOPER_MISSING"
	webMissingWorkerBigQueryJobUser    = "WORKER_ROLE_BIGQUERY_JOB_USER_MISSING"
	webMissingWorkerBigQueryDataEditor = "WORKER_ROLE_BIGQUERY_DATA_EDITOR_MISSING"
	webMissingWorkerArtifactReader     = "WORKER_ROLE_ARTIFACT_READER_MISSING"
	webMissingWorkerStorageAdmin       = "WORKER_ROLE_STORAGE_OBJECT_ADMIN_MISSING"
	webMissingDataset                  = "MIGRATION_DATASET_MISSING"
	webMissingDatasetLocation          = "MIGRATION_DATASET_LOCATION_MISMATCH"
	webMissingStagingBucket            = "STAGING_BUCKET_MISSING"
	webMissingStagingBucketLocation    = "STAGING_BUCKET_LOCATION_MISMATCH"
	webMissingStagingBucketUniformIAM  = "STAGING_BUCKET_UNIFORM_IAM_DISABLED"
	webMissingDriverRepository         = "DRIVER_REPOSITORY_MISSING"
	webMissingDriverRepositoryConfig   = "DRIVER_REPOSITORY_CONFIGURATION_INVALID"
)

var (
	webGooglePrincipalPattern        = regexp.MustCompile(`^serviceAccount:[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$`)
	webGoogleWorkerPrefixPattern     = regexp.MustCompile(`^[a-z][a-z0-9-]{1,20}-$`)
	webGoogleRepositorySuffixPattern = regexp.MustCompile(`^-[a-z][a-z0-9-]{0,20}$`)
	webGoogleDatasetSuffixPattern    = regexp.MustCompile(`^_[A-Za-z][A-Za-z0-9_]{0,30}$`)
	webGoogleResourceNamePattern     = regexp.MustCompile(`^[a-z][a-z0-9-]*[a-z0-9]$`)
)

var errWebGoogleCloudProbe = errors.New("google cloud capability probe failed")

var webGoogleRequiredServices = []struct {
	name    string
	missing string
}{
	{"aiplatform.googleapis.com", webMissingServiceVertexAI},
	{"artifactregistry.googleapis.com", webMissingServiceArtifactRegistry},
	{"bigquery.googleapis.com", webMissingServiceBigQuery},
	{"dataflow.googleapis.com", webMissingServiceDataflow},
	{"iam.googleapis.com", webMissingServiceIAM},
	{"iamcredentials.googleapis.com", webMissingServiceIAMCredentials},
	{"storage.googleapis.com", webMissingServiceStorage},
}

var webGoogleVerifierRoles = []struct {
	role    string
	missing string
}{
	{"roles/artifactregistry.reader", webMissingVerifierArtifactReader},
	{"roles/bigquery.metadataViewer", webMissingVerifierBigQueryMetadata},
	{"roles/iam.securityReviewer", webMissingVerifierSecurityReviewer},
	{"roles/serviceusage.serviceUsageViewer", webMissingVerifierServiceUsageViewer},
	{"roles/storage.viewer", webMissingVerifierStorageViewer},
}

var webGoogleWorkerRoles = []struct {
	role    string
	missing string
}{
	{"roles/artifactregistry.reader", webMissingWorkerArtifactReader},
	{"roles/bigquery.dataEditor", webMissingWorkerBigQueryDataEditor},
	{"roles/bigquery.jobUser", webMissingWorkerBigQueryJobUser},
	{"roles/dataflow.developer", webMissingWorkerDataflowDeveloper},
	{"roles/dataflow.worker", webMissingWorkerDataflowWorker},
	{"roles/storage.objectAdmin", webMissingWorkerStorageAdmin},
}

// WebGoogleCloudProbeConfig binds the verifier to the resource naming scheme
// emitted by the reviewed setup command. No credential or token field exists.
type WebGoogleCloudProbeConfig struct {
	AppVerifierPrincipal       string
	WorkerServiceAccountPrefix string
	DriverRepositorySuffix     string
	DatasetSuffix              string
	OverallTimeout             time.Duration
	RequestTimeout             time.Duration
}

type webGoogleBucket struct {
	Name       string
	Location   string
	UniformIAM bool
}

type webGoogleRepository struct {
	Name           string
	Format         string
	Mode           string
	MavenCentral   bool
	HasCredentials bool
}

type webGoogleCloudAPI interface {
	ServiceEnabled(context.Context, string, string) (bool, error)
	ProjectRoleMembers(context.Context, string) (map[string]map[string]bool, error)
	WorkerServiceAccount(context.Context, string, string) (bool, error)
	DatasetLocation(context.Context, string, string) (string, bool, error)
	Bucket(context.Context, string) (webGoogleBucket, bool, error)
	Repository(context.Context, string, string, string) (webGoogleRepository, bool, error)
}

// WebGoogleCloudCapabilityProber performs only read operations through ADC.
type WebGoogleCloudCapabilityProber struct {
	config WebGoogleCloudProbeConfig
	api    webGoogleCloudAPI
}

// NewWebGoogleCloudCapabilityProber creates official Google API clients using
// ADC. It does not make a cloud API request until ProbeCloudCapabilities.
func NewWebGoogleCloudCapabilityProber(ctx context.Context, config WebGoogleCloudProbeConfig) (*WebGoogleCloudCapabilityProber, error) {
	config, err := webValidateGoogleCloudProbeConfig(config)
	if err != nil {
		return nil, err
	}
	readOnlyOptions := []option.ClientOption{option.WithScopes(webGoogleCloudReadOnlyScope)}
	services, err := serviceusage.NewService(ctx, readOnlyOptions...)
	if err != nil {
		return nil, errWebGoogleCloudProbe
	}
	resources, err := cloudresourcemanager.NewService(ctx, readOnlyOptions...)
	if err != nil {
		return nil, errWebGoogleCloudProbe
	}
	identities, err := iam.NewService(ctx, option.WithScopes(webGoogleCloudIAMScope))
	if err != nil {
		return nil, errWebGoogleCloudProbe
	}
	datasets, err := bigquery.NewService(ctx, readOnlyOptions...)
	if err != nil {
		return nil, errWebGoogleCloudProbe
	}
	buckets, err := storage.NewService(ctx, readOnlyOptions...)
	if err != nil {
		return nil, errWebGoogleCloudProbe
	}
	repositories, err := artifactregistry.NewService(ctx, readOnlyOptions...)
	if err != nil {
		return nil, errWebGoogleCloudProbe
	}
	return &WebGoogleCloudCapabilityProber{config: config, api: &webGoogleOfficialAPI{
		services: services, resources: resources, identities: identities,
		datasets: datasets, buckets: buckets, repositories: repositories,
	}}, nil
}

func webValidateGoogleCloudProbeConfig(config WebGoogleCloudProbeConfig) (WebGoogleCloudProbeConfig, error) {
	principal, ok := webNormalizeGoogleServiceAccountPrincipal(config.AppVerifierPrincipal)
	if !ok ||
		!webGoogleWorkerPrefixPattern.MatchString(config.WorkerServiceAccountPrefix) ||
		!webGoogleRepositorySuffixPattern.MatchString(config.DriverRepositorySuffix) ||
		!webGoogleDatasetSuffixPattern.MatchString(config.DatasetSuffix) ||
		config.WorkerServiceAccountPrefix != "ztm-" || config.DriverRepositorySuffix != "-drivers" ||
		config.DatasetSuffix != "_migration" {
		return WebGoogleCloudProbeConfig{}, errWebGoogleCloudProbe
	}
	config.AppVerifierPrincipal = principal
	if config.OverallTimeout == 0 {
		config.OverallTimeout = 30 * time.Second
	}
	if config.RequestTimeout == 0 {
		config.RequestTimeout = 5 * time.Second
	}
	if config.OverallTimeout < time.Second || config.OverallTimeout > 2*time.Minute ||
		config.RequestTimeout < 100*time.Millisecond || config.RequestTimeout > 30*time.Second ||
		config.RequestTimeout > config.OverallTimeout {
		return WebGoogleCloudProbeConfig{}, errWebGoogleCloudProbe
	}
	return config, nil
}

func webNormalizeGoogleServiceAccountPrincipal(value string) (string, bool) {
	if !strings.HasPrefix(value, "serviceAccount:") {
		value = "serviceAccount:" + value
	}
	return value, webGooglePrincipalPattern.MatchString(value)
}

func newWebGoogleCloudCapabilityProberForTest(config WebGoogleCloudProbeConfig, api webGoogleCloudAPI) (*WebGoogleCloudCapabilityProber, error) {
	config, err := webValidateGoogleCloudProbeConfig(config)
	if err != nil || api == nil {
		return nil, errWebGoogleCloudProbe
	}
	return &WebGoogleCloudCapabilityProber{config: config, api: api}, nil
}

func (p *WebGoogleCloudCapabilityProber) requestContext(parent context.Context) (context.Context, context.CancelFunc) {
	return context.WithTimeout(parent, p.config.RequestTimeout)
}

// VerifierPrincipal exposes only the deployment-owned, non-secret IAM member
// that the reviewed setup command must grant read-only verification access.
func (p *WebGoogleCloudCapabilityProber) VerifierPrincipal() string {
	if p == nil {
		return ""
	}
	return p.config.AppVerifierPrincipal
}

// ProbeCloudCapabilities verifies services, the app verifier's read-only IAM
// roles, the dedicated worker and its roles, and the exact dataset, bucket and
// Maven Central remote repository. Upstream errors are collapsed to one closed
// error; only closed capability identifiers are returned.
func (p *WebGoogleCloudCapabilityProber) ProbeCloudCapabilities(ctx context.Context, setup WebCloudSetupRecord) ([]string, error) {
	if p == nil || p.api == nil || !p.validSetupBinding(setup) {
		return nil, errWebGoogleCloudProbe
	}
	projectID, region := setup.ProjectID, setup.Region
	overall, cancel := context.WithTimeout(ctx, p.config.OverallTimeout)
	defer cancel()
	missing := make(map[string]bool)
	enabled := make(map[string]bool, len(webGoogleRequiredServices))
	for _, service := range webGoogleRequiredServices {
		request, done := p.requestContext(overall)
		isEnabled, err := p.api.ServiceEnabled(request, projectID, service.name)
		done()
		if err != nil {
			return nil, errWebGoogleCloudProbe
		}
		enabled[service.name] = isEnabled
		if !isEnabled {
			missing[service.missing] = true
		}
	}

	request, done := p.requestContext(overall)
	roleMembers, err := p.api.ProjectRoleMembers(request, projectID)
	done()
	if err != nil {
		return nil, errWebGoogleCloudProbe
	}
	for _, required := range webGoogleVerifierRoles {
		if !roleMembers[required.role][p.config.AppVerifierPrincipal] {
			missing[required.missing] = true
		}
	}

	if enabled["bigquery.googleapis.com"] {
		request, done = p.requestContext(overall)
		location, found, err := p.api.DatasetLocation(request, projectID, setup.DatasetPrefix+p.config.DatasetSuffix)
		done()
		if err != nil {
			return nil, errWebGoogleCloudProbe
		}
		if !found {
			missing[webMissingDataset] = true
		} else if !strings.EqualFold(location, region) {
			missing[webMissingDatasetLocation] = true
		}
	}

	if enabled["iam.googleapis.com"] {
		request, done = p.requestContext(overall)
		workerEmail := setup.ServiceAccountName + "@" + projectID + ".iam.gserviceaccount.com"
		workerFound, err := p.api.WorkerServiceAccount(request, projectID, workerEmail)
		done()
		if err != nil {
			return nil, errWebGoogleCloudProbe
		}
		if !workerFound {
			missing[webMissingWorkerAccount] = true
		} else {
			workerMissing, err := p.exactWorkerCapabilities(overall, setup, roleMembers, enabled)
			if err != nil {
				return nil, errWebGoogleCloudProbe
			}
			for _, code := range workerMissing {
				missing[code] = true
			}
		}
	}

	result := make([]string, 0, len(missing))
	for code := range missing {
		result = append(result, code)
	}
	sort.Strings(result)
	return result, nil
}

func (p *WebGoogleCloudCapabilityProber) validSetupBinding(setup WebCloudSetupRecord) bool {
	setupSuffix := strings.TrimPrefix(setup.SetupID, "setup_")
	if len(setupSuffix) < 12 {
		return false
	}
	expectedResourcePrefix := p.config.WorkerServiceAccountPrefix + setupSuffix[:12]
	return webProjectIDPattern.MatchString(setup.ProjectID) && webRegionPattern.MatchString(setup.Region) &&
		webDatasetPrefixPattern.MatchString(setup.DatasetPrefix) && webSetupIDPattern.MatchString(setup.SetupID) &&
		setup.ResourcePrefix == expectedResourcePrefix && setup.ServiceAccountName == expectedResourcePrefix &&
		webValidGoogleResourceName(setup.ServiceAccountName) &&
		setup.RepositoryName == setup.ServiceAccountName+p.config.DriverRepositorySuffix &&
		setup.BucketName == setup.ProjectID+"-"+setup.ResourcePrefix
}

func webValidGoogleResourceName(value string) bool {
	return len(value) >= 3 && len(value) <= 63 && webGoogleResourceNamePattern.MatchString(value)
}

func (p *WebGoogleCloudCapabilityProber) exactWorkerCapabilities(ctx context.Context, setup WebCloudSetupRecord, roleMembers map[string]map[string]bool, enabled map[string]bool) ([]string, error) {
	member := "serviceAccount:" + setup.ServiceAccountName + "@" + setup.ProjectID + ".iam.gserviceaccount.com"
	missing := make([]string, 0)
	for _, required := range webGoogleWorkerRoles {
		if !roleMembers[required.role][member] {
			missing = append(missing, required.missing)
		}
	}
	if enabled["storage.googleapis.com"] {
		request, done := p.requestContext(ctx)
		bucket, found, err := p.api.Bucket(request, setup.BucketName)
		done()
		if err != nil {
			return nil, errWebGoogleCloudProbe
		}
		if !found {
			missing = append(missing, webMissingStagingBucket)
		} else {
			if bucket.Name != setup.BucketName || !strings.EqualFold(bucket.Location, setup.Region) {
				missing = append(missing, webMissingStagingBucketLocation)
			}
			if !bucket.UniformIAM {
				missing = append(missing, webMissingStagingBucketUniformIAM)
			}
		}
	}
	if enabled["artifactregistry.googleapis.com"] {
		request, done := p.requestContext(ctx)
		repository, found, err := p.api.Repository(request, setup.ProjectID, setup.Region, setup.RepositoryName)
		done()
		if err != nil {
			return nil, errWebGoogleCloudProbe
		}
		expectedName := fmt.Sprintf("projects/%s/locations/%s/repositories/%s", setup.ProjectID, setup.Region, setup.RepositoryName)
		if !found {
			missing = append(missing, webMissingDriverRepository)
		} else if repository.Name != expectedName || repository.Format != "MAVEN" || repository.Mode != "REMOTE_REPOSITORY" ||
			!repository.MavenCentral || repository.HasCredentials {
			missing = append(missing, webMissingDriverRepositoryConfig)
		}
	}
	sort.Strings(missing)
	return missing, nil
}

type webGoogleOfficialAPI struct {
	services     *serviceusage.Service
	resources    *cloudresourcemanager.Service
	identities   *iam.Service
	datasets     *bigquery.Service
	buckets      *storage.Service
	repositories *artifactregistry.Service
}

func (api *webGoogleOfficialAPI) ServiceEnabled(ctx context.Context, projectID, serviceName string) (bool, error) {
	service, err := api.services.Services.Get(fmt.Sprintf("projects/%s/services/%s", projectID, serviceName)).Context(ctx).Do()
	if err != nil {
		return false, err
	}
	return service.State == "ENABLED", nil
}

func (api *webGoogleOfficialAPI) ProjectRoleMembers(ctx context.Context, projectID string) (map[string]map[string]bool, error) {
	policy, err := api.resources.Projects.GetIamPolicy(projectID, &cloudresourcemanager.GetIamPolicyRequest{}).Context(ctx).Do()
	if err != nil {
		return nil, err
	}
	result := make(map[string]map[string]bool)
	for _, binding := range policy.Bindings {
		if binding == nil || binding.Condition != nil {
			continue
		}
		if result[binding.Role] == nil {
			result[binding.Role] = make(map[string]bool)
		}
		for _, member := range binding.Members {
			result[binding.Role][member] = true
		}
	}
	return result, nil
}

func (api *webGoogleOfficialAPI) WorkerServiceAccount(ctx context.Context, projectID, email string) (bool, error) {
	name := fmt.Sprintf("projects/%s/serviceAccounts/%s", projectID, email)
	account, err := api.identities.Projects.ServiceAccounts.Get(name).Context(ctx).Do()
	if webGoogleNotFound(err) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return account != nil && !account.Disabled && account.Email == email, nil
}

func (api *webGoogleOfficialAPI) DatasetLocation(ctx context.Context, projectID, datasetID string) (string, bool, error) {
	dataset, err := api.datasets.Datasets.Get(projectID, datasetID).Context(ctx).Do()
	if webGoogleNotFound(err) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	return dataset.Location, true, nil
}

func (api *webGoogleOfficialAPI) Bucket(ctx context.Context, bucketName string) (webGoogleBucket, bool, error) {
	bucket, err := api.buckets.Buckets.Get(bucketName).Context(ctx).Do()
	if webGoogleNotFound(err) {
		return webGoogleBucket{}, false, nil
	}
	if err != nil {
		return webGoogleBucket{}, false, err
	}
	uniform := bucket.IamConfiguration != nil && bucket.IamConfiguration.UniformBucketLevelAccess != nil &&
		bucket.IamConfiguration.UniformBucketLevelAccess.Enabled
	return webGoogleBucket{Name: bucket.Name, Location: bucket.Location, UniformIAM: uniform}, true, nil
}

func (api *webGoogleOfficialAPI) Repository(ctx context.Context, projectID, region, repositoryID string) (webGoogleRepository, bool, error) {
	name := fmt.Sprintf("projects/%s/locations/%s/repositories/%s", projectID, region, repositoryID)
	repository, err := api.repositories.Projects.Locations.Repositories.Get(name).Context(ctx).Do()
	if webGoogleNotFound(err) {
		return webGoogleRepository{}, false, nil
	}
	if err != nil {
		return webGoogleRepository{}, false, err
	}
	mavenCentral := repository.RemoteRepositoryConfig != nil && repository.RemoteRepositoryConfig.MavenRepository != nil &&
		repository.RemoteRepositoryConfig.MavenRepository.PublicRepository == "MAVEN_CENTRAL"
	hasCredentials := repository.RemoteRepositoryConfig != nil && repository.RemoteRepositoryConfig.UpstreamCredentials != nil
	return webGoogleRepository{Name: repository.Name, Format: repository.Format, Mode: repository.Mode, MavenCentral: mavenCentral, HasCredentials: hasCredentials}, true, nil
}

func webGoogleNotFound(err error) bool {
	var apiError *googleapi.Error
	return errors.As(err, &apiError) && apiError.Code == 404
}
