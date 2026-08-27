package main

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"net/http"
	"sort"
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
	webWriteJSON(w, http.StatusOK, WebCloudConnectionResponse{SchemaVersion: WebSchemaVersion, Status: record.Status, SetupID: record.SetupID, ProjectID: record.ProjectID, Region: record.Region, DatasetPrefix: record.DatasetPrefix, VerifiedAt: record.VerifiedAt, MissingCapabilities: record.MissingCapabilities})
}

func (h *webBFFHandler) handleCloudSetup(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodPost) || !h.allowMutation(w, r) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
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
	command := fmt.Sprintf("set -euo pipefail\ngcloud services enable aiplatform.googleapis.com dataflow.googleapis.com bigquery.googleapis.com --project=%s\nbq --project_id=%s mk --dataset --location=%s %s:%s_migration\nprintf '%%s\\n' '%s'", req.ProjectID, req.ProjectID, req.Region, req.ProjectID, req.DatasetPrefix, receipt)
	commandSum := webSHA256(command)
	now := h.now().UTC()
	expires := now.Add(h.setupTTL)
	record := WebCloudSetupRecord{SetupID: setupID, OwnerUID: identity.Subject, ProjectID: req.ProjectID, Region: req.Region, DatasetPrefix: req.DatasetPrefix, CommandDigest: "sha256:" + commandSum, ReceiptSHA256: webSHA256(receipt), Status: webCloudSetupPending, CreatedAt: h.stamp(now), ExpiresAt: h.stamp(expires)}
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
	record, found := h.store.CloudSetup(identity.Subject, req.SetupID)
	if !found {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	if record.Status == webCloudSetupVerified {
		webWriteProblem(w, webErrCloudReceiptInvalid)
		return
	}
	expires, valid := cpParseStamp(record.ExpiresAt)
	if !valid || !h.now().UTC().Before(expires) {
		webWriteProblem(w, webErrCloudSetupExpired)
		return
	}
	actual := webSHA256(req.Receipt)
	if subtle.ConstantTimeCompare([]byte(actual), []byte(record.ReceiptSHA256)) != 1 {
		webWriteProblem(w, webErrCloudReceiptInvalid)
		return
	}
	if h.cloudProber == nil {
		webWriteProblem(w, webErrCloudUnavailable)
		return
	}
	missing, err := h.cloudProber.ProbeCloudCapabilities(r.Context(), record.ProjectID, record.Region, record.DatasetPrefix)
	if err != nil || !webValidCapabilityList(missing) {
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
