package main

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strings"
)

func webRandomHex(bytes int) (string, error) {
	raw := make([]byte, bytes)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	return hex.EncodeToString(raw), nil
}

func webSHA256(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}

func (h *webBFFHandler) handleCloudConnection(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodGet) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	setups := h.store.CloudSetupsForOwner(identity.Subject)
	if len(setups) == 0 {
		webWriteJSON(w, http.StatusOK, WebCloudConnectionResponse{SchemaVersion: WebSchemaVersion, Status: "not_connected"})
		return
	}
	record := setups[len(setups)-1]
	status := record.Status
	if status == webCloudSetupVerifying {
		status = webCloudSetupPending
	}
	webWriteJSON(w, http.StatusOK, WebCloudConnectionResponse{SchemaVersion: WebSchemaVersion, Status: status, SetupID: record.SetupID, ProjectID: record.ProjectID, Region: record.Region, DatasetPrefix: record.DatasetPrefix, VerifiedAt: record.VerifiedAt, MissingCapabilities: record.MissingCapabilities})
}

func (h *webBFFHandler) handleCloudSetup(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodPost) || !h.allowMutation(w, r) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	if h.cloudProber == nil {
		webWriteProblem(w, webErrCloudUnavailable)
		return
	}
	var req WebCloudSetupRequest
	if err := webDecodeJSON(w, r, &req, webMaxJSONBody); err != nil {
		webWriteProblem(w, err)
		return
	}
	if req.SchemaVersion != WebSchemaVersion || !webProjectIDPattern.MatchString(req.ProjectID) || !webRegionPattern.MatchString(req.Region) || !webDatasetPrefixPattern.MatchString(req.DatasetPrefix) {
		webWriteProblem(w, cpErrInvalidRequest)
		return
	}
	idPart, err := webRandomHex(12)
	if err != nil {
		webWriteProblem(w, cpErrInternal)
		return
	}
	receipt, err := webRandomHex(32)
	if err != nil {
		webWriteProblem(w, cpErrInternal)
		return
	}
	setupID := "setup_" + idPart
	serviceAccountName := "ztm-" + idPart[:12]
	serviceAccountEmail := serviceAccountName + "@" + req.ProjectID + ".iam.gserviceaccount.com"
	repositoryName := serviceAccountName + "-drivers"
	bucketName := req.ProjectID + "-" + serviceAccountName
	command := strings.Join([]string{
		"set -euo pipefail",
		fmt.Sprintf("gcloud services enable aiplatform.googleapis.com dataflow.googleapis.com bigquery.googleapis.com artifactregistry.googleapis.com iam.googleapis.com iamcredentials.googleapis.com storage.googleapis.com --project=%s --quiet", req.ProjectID),
		fmt.Sprintf("gcloud iam service-accounts describe %s --project=%s >/dev/null 2>&1 || gcloud iam service-accounts create %s --project=%s --display-name='Zero Trust Migration Worker'", serviceAccountEmail, req.ProjectID, serviceAccountName, req.ProjectID),
		fmt.Sprintf("for role in roles/dataflow.worker roles/dataflow.developer roles/bigquery.jobUser roles/bigquery.dataEditor roles/artifactregistry.reader roles/storage.objectAdmin; do gcloud projects add-iam-policy-binding %s --member=serviceAccount:%s --role=\"$role\" --condition=None --quiet >/dev/null; done", req.ProjectID, serviceAccountEmail),
		fmt.Sprintf("for role in roles/serviceusage.serviceUsageViewer roles/iam.securityReviewer roles/bigquery.metadataViewer roles/artifactregistry.reader roles/storage.viewer roles/aiplatform.user; do gcloud projects add-iam-policy-binding %s --member=%s --role=\"$role\" --condition=None --quiet >/dev/null; done", req.ProjectID, h.cloudVerifierPrincipal),
		fmt.Sprintf("bq --project_id=%s show %s:%s_migration >/dev/null 2>&1 || bq --project_id=%s mk --dataset --location=%s %s:%s_migration", req.ProjectID, req.ProjectID, req.DatasetPrefix, req.ProjectID, req.Region, req.ProjectID, req.DatasetPrefix),
		fmt.Sprintf("gcloud storage buckets describe gs://%s --project=%s >/dev/null 2>&1 || gcloud storage buckets create gs://%s --project=%s --location=%s --uniform-bucket-level-access", bucketName, req.ProjectID, bucketName, req.ProjectID, req.Region),
		fmt.Sprintf("gcloud artifacts repositories describe %s --project=%s --location=%s >/dev/null 2>&1 || gcloud artifacts repositories create %s --project=%s --location=%s --repository-format=maven --mode=remote-repository --remote-mvn-repo=maven-central --description='Governed JDBC driver remote'", repositoryName, req.ProjectID, req.Region, repositoryName, req.ProjectID, req.Region),
		fmt.Sprintf("printf '%%s\\n' '%s'", receipt),
	}, "\n")
	commandSum := webSHA256(command)
	now := h.now().UTC()
	expires := now.Add(h.setupTTL)
	record := WebCloudSetupRecord{
		SetupID: setupID, OwnerUID: identity.Subject, ProjectID: req.ProjectID, Region: req.Region,
		DatasetPrefix: req.DatasetPrefix, ResourcePrefix: serviceAccountName,
		ServiceAccountName: serviceAccountName, RepositoryName: repositoryName, BucketName: bucketName,
		CommandDigest: "sha256:" + commandSum, ReceiptSHA256: webSHA256(receipt),
		Status: webCloudSetupPending, CreatedAt: h.stamp(now), ExpiresAt: h.stamp(expires),
	}
	if err := h.store.PutCloudSetup(record); err != nil {
		webWriteProblem(w, cpErrInternal)
		return
	}
	webWriteJSON(w, http.StatusCreated, WebCloudSetupResponse{SchemaVersion: WebSchemaVersion, SetupID: setupID, ProjectID: req.ProjectID, Region: req.Region, Command: command, CommandDigest: record.CommandDigest, ExpiresAt: record.ExpiresAt})
}

func (h *webBFFHandler) handleCloudVerify(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodPost) || !h.allowMutation(w, r) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	var req WebCloudVerifyRequest
	if err := webDecodeJSON(w, r, &req, webMaxJSONBody); err != nil {
		webWriteProblem(w, err)
		return
	}
	if req.SchemaVersion != WebSchemaVersion || !webSetupIDPattern.MatchString(req.SetupID) || !webNoncePattern.MatchString(req.Receipt) {
		webWriteProblem(w, cpErrInvalidRequest)
		return
	}
	if h.cloudProber == nil {
		webWriteProblem(w, webErrCloudUnavailable)
		return
	}
	record, err := h.store.BeginCloudVerification(identity.Subject, req.SetupID, webSHA256(req.Receipt), h.stamp(h.now()))
	if errors.Is(err, errWebStoreNotFound) {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	if errors.Is(err, errWebStoreExpired) {
		webWriteProblem(w, webErrCloudSetupExpired)
		return
	}
	if err != nil {
		webWriteProblem(w, webErrCloudReceiptInvalid)
		return
	}
	missing, err := h.cloudProber.ProbeCloudCapabilities(r.Context(), record)
	if err != nil || !webValidCapabilityList(missing) {
		_, _ = h.store.RecordCloudVerification(identity.Subject, record.SetupID, h.stamp(h.now()), []string{"CAPABILITY_PROBE_FAILED"})
		webWriteProblem(w, cpErrInternal)
		return
	}
	sort.Strings(missing)
	verified, err := h.store.RecordCloudVerification(identity.Subject, record.SetupID, h.stamp(h.now()), missing)
	if err != nil {
		webWriteProblem(w, cpErrInternal)
		return
	}
	status := "incomplete"
	if verified.Status == webCloudSetupVerified {
		status = "verified"
	}
	verifiedAt := verified.VerifiedAt
	if verifiedAt == "" {
		verifiedAt = h.stamp(h.now())
	}
	webWriteJSON(w, http.StatusOK, WebCloudVerifyResponse{SchemaVersion: WebSchemaVersion, SetupID: verified.SetupID, Status: status, ProjectID: verified.ProjectID, Region: verified.Region, VerifiedAt: verifiedAt, MissingCapabilities: append([]string(nil), missing...)})
}
