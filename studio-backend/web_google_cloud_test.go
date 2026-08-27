package main

import (
	"context"
	"errors"
	"reflect"
	"sort"
	"testing"
	"time"

	"google.golang.org/api/googleapi"
)

type webFakeGoogleCloudAPI struct {
	services     map[string]bool
	roles        map[string]map[string]bool
	workers      map[string]bool
	datasets     map[string]string
	buckets      map[string]webGoogleBucket
	repositories map[string]webGoogleRepository
	failure      error
	block        bool
}

func (f *webFakeGoogleCloudAPI) wait(ctx context.Context) error {
	if f.block {
		<-ctx.Done()
		return ctx.Err()
	}
	return f.failure
}

func (f *webFakeGoogleCloudAPI) ServiceEnabled(ctx context.Context, _, service string) (bool, error) {
	if err := f.wait(ctx); err != nil {
		return false, err
	}
	return f.services[service], nil
}

func (f *webFakeGoogleCloudAPI) ProjectRoleMembers(ctx context.Context, _ string) (map[string]map[string]bool, error) {
	if err := f.wait(ctx); err != nil {
		return nil, err
	}
	return f.roles, nil
}

func (f *webFakeGoogleCloudAPI) WorkerServiceAccount(ctx context.Context, _, email string) (bool, error) {
	if err := f.wait(ctx); err != nil {
		return false, err
	}
	return f.workers[email], nil
}

func (f *webFakeGoogleCloudAPI) DatasetLocation(ctx context.Context, _, dataset string) (string, bool, error) {
	if err := f.wait(ctx); err != nil {
		return "", false, err
	}
	location, found := f.datasets[dataset]
	return location, found, nil
}

func (f *webFakeGoogleCloudAPI) Bucket(ctx context.Context, bucket string) (webGoogleBucket, bool, error) {
	if err := f.wait(ctx); err != nil {
		return webGoogleBucket{}, false, err
	}
	value, found := f.buckets[bucket]
	return value, found, nil
}

func (f *webFakeGoogleCloudAPI) Repository(ctx context.Context, project, region, repository string) (webGoogleRepository, bool, error) {
	if err := f.wait(ctx); err != nil {
		return webGoogleRepository{}, false, err
	}
	value, found := f.repositories[project+"/"+region+"/"+repository]
	return value, found, nil
}

func webTestGoogleCloudProbeConfig() WebGoogleCloudProbeConfig {
	return WebGoogleCloudProbeConfig{
		AppVerifierPrincipal:       "serviceAccount:verifier@owner-project1.iam.gserviceaccount.com",
		WorkerServiceAccountPrefix: "ztm-",
		DriverRepositorySuffix:     "-drivers",
		DatasetSuffix:              "_migration",
		OverallTimeout:             2 * time.Second,
		RequestTimeout:             200 * time.Millisecond,
	}
}

func webCompleteGoogleCloudAPI(config WebGoogleCloudProbeConfig, project, region, datasetPrefix, worker string) *webFakeGoogleCloudAPI {
	services := make(map[string]bool)
	for _, required := range webGoogleRequiredServices {
		services[required.name] = true
	}
	roles := make(map[string]map[string]bool)
	for _, required := range webGoogleVerifierRoles {
		roles[required.role] = map[string]bool{config.AppVerifierPrincipal: true}
	}
	workerEmail := worker + "@" + project + ".iam.gserviceaccount.com"
	workerMember := "serviceAccount:" + workerEmail
	for _, required := range webGoogleWorkerRoles {
		if roles[required.role] == nil {
			roles[required.role] = make(map[string]bool)
		}
		roles[required.role][workerMember] = true
	}
	bucketName := project + "-" + worker
	repositoryID := worker + config.DriverRepositorySuffix
	repositoryKey := project + "/" + region + "/" + repositoryID
	repositoryName := "projects/" + project + "/locations/" + region + "/repositories/" + repositoryID
	return &webFakeGoogleCloudAPI{
		services: services, roles: roles, workers: map[string]bool{workerEmail: true},
		datasets: map[string]string{datasetPrefix + config.DatasetSuffix: region},
		buckets:  map[string]webGoogleBucket{bucketName: {Name: bucketName, Location: region, UniformIAM: true}},
		repositories: map[string]webGoogleRepository{repositoryKey: {
			Name: repositoryName, Format: "MAVEN", Mode: "REMOTE_REPOSITORY", MavenCentral: true,
		}},
	}
}

func webTestGoogleCloudSetup(project, region, datasetPrefix, suffix string) WebCloudSetupRecord {
	resourcePrefix := "ztm-" + suffix
	return WebCloudSetupRecord{
		SetupID: "setup_" + suffix, ProjectID: project, Region: region, DatasetPrefix: datasetPrefix,
		ResourcePrefix: resourcePrefix, ServiceAccountName: resourcePrefix,
		RepositoryName: resourcePrefix + "-drivers", BucketName: project + "-" + resourcePrefix,
	}
}

func TestWebGoogleCloudCapabilityProberAcceptsOnlyCompleteCorrelatedSetup(t *testing.T) {
	config := webTestGoogleCloudProbeConfig()
	api := webCompleteGoogleCloudAPI(config, "customer-project1", "us-central1", "demo", "ztm-123456789abc")
	probe, err := newWebGoogleCloudCapabilityProberForTest(config, api)
	if err != nil {
		t.Fatal(err)
	}
	missing, err := probe.ProbeCloudCapabilities(context.Background(), webTestGoogleCloudSetup("customer-project1", "us-central1", "demo", "123456789abc"))
	if err != nil {
		t.Fatal(err)
	}
	if len(missing) != 0 {
		t.Fatalf("missing = %v", missing)
	}
}

func TestWebGoogleCloudCapabilityProberReturnsClosedSortedMissingSet(t *testing.T) {
	config := webTestGoogleCloudProbeConfig()
	api := webCompleteGoogleCloudAPI(config, "customer-project1", "us-central1", "demo", "ztm-123456789abc")
	api.services["aiplatform.googleapis.com"] = false
	delete(api.roles["roles/serviceusage.serviceUsageViewer"], config.AppVerifierPrincipal)
	worker := "serviceAccount:ztm-123456789abc@customer-project1.iam.gserviceaccount.com"
	delete(api.roles["roles/dataflow.worker"], worker)
	api.datasets["demo_migration"] = "europe-west1"
	bucket := api.buckets["customer-project1-ztm-123456789abc"]
	bucket.UniformIAM = false
	api.buckets["customer-project1-ztm-123456789abc"] = bucket
	repository := api.repositories["customer-project1/us-central1/ztm-123456789abc-drivers"]
	repository.HasCredentials = true
	api.repositories["customer-project1/us-central1/ztm-123456789abc-drivers"] = repository
	probe, err := newWebGoogleCloudCapabilityProberForTest(config, api)
	if err != nil {
		t.Fatal(err)
	}
	missing, err := probe.ProbeCloudCapabilities(context.Background(), webTestGoogleCloudSetup("customer-project1", "us-central1", "demo", "123456789abc"))
	if err != nil {
		t.Fatal(err)
	}
	want := []string{
		webMissingDatasetLocation,
		webMissingDriverRepositoryConfig,
		webMissingServiceVertexAI,
		webMissingStagingBucketUniformIAM,
		webMissingVerifierServiceUsageViewer,
		webMissingWorkerDataflowWorker,
	}
	sort.Strings(want)
	if !reflect.DeepEqual(missing, want) {
		t.Fatalf("missing = %v, want %v", missing, want)
	}
	if !sort.StringsAreSorted(missing) {
		t.Fatal("missing capabilities are not sorted")
	}
}

func TestWebGoogleCloudCapabilityProberNeverUsesAStaleSetup(t *testing.T) {
	config := webTestGoogleCloudProbeConfig()
	api := webCompleteGoogleCloudAPI(config, "customer-project1", "us-central1", "demo", "ztm-aaaaaaaaaaaa")
	probe, err := newWebGoogleCloudCapabilityProberForTest(config, api)
	if err != nil {
		t.Fatal(err)
	}
	missing, err := probe.ProbeCloudCapabilities(context.Background(), webTestGoogleCloudSetup("customer-project1", "us-central1", "demo", "bbbbbbbbbbbb"))
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(missing, []string{webMissingWorkerAccount}) {
		t.Fatalf("stale setup was used; missing = %v", missing)
	}
}

func TestWebGoogleCloudCapabilityProberCollapsesUpstreamErrorsAndBoundsRequests(t *testing.T) {
	config := webTestGoogleCloudProbeConfig()
	config.RequestTimeout = 100 * time.Millisecond
	api := &webFakeGoogleCloudAPI{block: true}
	probe, err := newWebGoogleCloudCapabilityProberForTest(config, api)
	if err != nil {
		t.Fatal(err)
	}
	started := time.Now()
	_, err = probe.ProbeCloudCapabilities(context.Background(), webTestGoogleCloudSetup("customer-project1", "us-central1", "demo", "123456789abc"))
	if !errors.Is(err, errWebGoogleCloudProbe) || err.Error() != errWebGoogleCloudProbe.Error() {
		t.Fatalf("error = %v", err)
	}
	if elapsed := time.Since(started); elapsed > time.Second {
		t.Fatalf("request timeout was not bounded: %s", elapsed)
	}

	api = &webFakeGoogleCloudAPI{failure: errors.New("upstream secret diagnostic")}
	probe, err = newWebGoogleCloudCapabilityProberForTest(config, api)
	if err != nil {
		t.Fatal(err)
	}
	_, err = probe.ProbeCloudCapabilities(context.Background(), webTestGoogleCloudSetup("customer-project1", "us-central1", "demo", "123456789abc"))
	if err == nil || err.Error() != errWebGoogleCloudProbe.Error() {
		t.Fatalf("upstream diagnostic leaked: %v", err)
	}
}

func TestWebGoogleCloudCapabilityProberRejectsInvalidConfigBeforeADC(t *testing.T) {
	config := webTestGoogleCloudProbeConfig()
	config.AppVerifierPrincipal = "user:attacker@example.test"
	if _, err := NewWebGoogleCloudCapabilityProber(context.Background(), config); !errors.Is(err, errWebGoogleCloudProbe) {
		t.Fatalf("invalid config error = %v", err)
	}
	if !webGoogleNotFound(&googleapi.Error{Code: 404}) || webGoogleNotFound(&googleapi.Error{Code: 403}) {
		t.Fatal("Google API not-found classification is not closed")
	}
	config = webTestGoogleCloudProbeConfig()
	config.WorkerServiceAccountPrefix = "other-"
	if _, err := NewWebGoogleCloudCapabilityProber(context.Background(), config); !errors.Is(err, errWebGoogleCloudProbe) {
		t.Fatalf("mismatched naming config error = %v", err)
	}
}

func TestWebGoogleCloudCapabilityProberRejectsTamperedSetupBindingBeforeAPICalls(t *testing.T) {
	config := webTestGoogleCloudProbeConfig()
	api := webCompleteGoogleCloudAPI(config, "customer-project1", "us-central1", "demo", "ztm-123456789abc")
	probe, err := newWebGoogleCloudCapabilityProberForTest(config, api)
	if err != nil {
		t.Fatal(err)
	}
	setup := webTestGoogleCloudSetup("customer-project1", "us-central1", "demo", "123456789abc")
	setup.RepositoryName = "ztm-stale-drivers"
	if _, err := probe.ProbeCloudCapabilities(context.Background(), setup); !errors.Is(err, errWebGoogleCloudProbe) {
		t.Fatalf("tampered setup error = %v", err)
	}
}
