package main

// web_demos.go serves the anonymous immutable recorded-demo surface and the
// owner-only publication endpoint.
//
// Published demos are create-only and content addressed, so both the
// per-demo and per-digest reads are served with strong ETags and public
// caching. Publication itself runs the frozen WebDemoPublisher gate against
// the caller's own server-side trusted run record; the browser can neither
// classify a run, name its owner, nor vouch for its evidence.

import (
	"net/http"
	"strings"
)

const (
	webDemoListCacheControl   = "public, max-age=60"
	webDemoCacheControl       = "public, max-age=3600"
	webDemoBundleCacheControl = "public, max-age=31536000, immutable"
)

func webStrongETag(bundleDigest string) string {
	return `"` + bundleDigest + `"`
}

// webIfNoneMatchHit reports whether any presented validator matches the
// strong ETag (weak comparison, per RFC 9110 for If-None-Match).
func webIfNoneMatchHit(r *http.Request, etag string) bool {
	for _, headerValue := range r.Header.Values("If-None-Match") {
		for _, candidate := range strings.Split(headerValue, ",") {
			candidate = strings.TrimSpace(candidate)
			if candidate == "*" || candidate == etag || candidate == "W/"+etag {
				return true
			}
		}
	}
	return false
}

func (h *webBFFHandler) handleDemoList(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodGet) {
		return
	}
	w.Header().Set("Cache-Control", webDemoListCacheControl)
	webWriteJSON(w, http.StatusOK, WebListDemosResponse{
		SchemaVersion: WebSchemaVersion,
		Demos:         h.store.PublishedDemoSummaries(),
	})
}

// writePublishedManifest serves the stored, already-validated manifest bytes
// verbatim with immutable caching semantics.
func webWritePublishedManifest(w http.ResponseWriter, r *http.Request, record WebPublicationRecord, cacheControl string) {
	etag := webStrongETag(record.BundleDigest)
	w.Header().Set("Cache-Control", cacheControl)
	w.Header().Set("ETag", etag)
	if webIfNoneMatchHit(r, etag) {
		w.WriteHeader(http.StatusNotModified)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(record.ManifestJSON)
}

func (h *webBFFHandler) handleDemoByID(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodGet) {
		return
	}
	demoID := r.PathValue("demo_id")
	if !webDemoIDPattern.MatchString(demoID) {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	record, ok := h.store.PublishedDemoByID(demoID)
	if !ok {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	webWritePublishedManifest(w, r, record, webDemoCacheControl)
}

func (h *webBFFHandler) handleDemoByDigest(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodGet) {
		return
	}
	digest := r.PathValue("bundle_digest")
	if !validWebDigest(digest) {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	record, ok := h.store.PublishedDemoByDigest(digest)
	if !ok {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	webWritePublishedManifest(w, r, record, webDemoBundleCacheControl)
}

func (h *webBFFHandler) handlePublishDemo(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodPost) {
		return
	}
	if !h.allowMutation(w, r) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	if h.artifacts == nil {
		webWriteProblem(w, webErrPublicationUnavailable)
		return
	}
	var req WebPublishDemoRequest
	if err := webDecodeJSON(w, r, &req, WebMaxPublicationBytes); err != nil {
		webWriteProblem(w, err)
		return
	}
	if req.SchemaVersion != WebSchemaVersion {
		webWriteProblem(w, cpErrInvalidRequest)
		return
	}
	// Owner-only: publication requires the caller's own server-side trusted
	// record for the manifest's source run. A foreign or unknown run is
	// indistinguishable from a missing one.
	trusted, ok := h.store.TrustedPublicationRecord(identity.Subject, req.Manifest.SourceRunID)
	if !ok {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	publisher := WebDemoPublisher{Artifacts: h.artifacts, Store: h.store}
	result, err := publisher.Publish(r.Context(), WebPublishDemoInput{
		Manifest: req.Manifest,
		Trusted:  trusted,
	})
	if err != nil {
		webWriteProblem(w, err)
		return
	}
	w.Header().Set("Location", result.Location)
	webWriteJSON(w, http.StatusCreated, WebPublishDemoResponse{
		SchemaVersion: WebSchemaVersion,
		DemoID:        result.DemoID,
		PublishedAt:   req.Manifest.PublishedAt,
		BundleDigest:  result.BundleDigest,
		Location:      result.Location,
	})
}
