package main

import (
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

type webSPAHandler struct {
	root  string
	index string
}

func newWebSPAHandler(root string) (http.Handler, error) {
	abs, err := filepath.Abs(strings.TrimSpace(root))
	if err != nil || root == "" {
		return nil, errors.New("web spa: a build directory is required")
	}
	real, err := filepath.EvalSymlinks(abs)
	if err != nil {
		return nil, errors.New("web spa: build directory is unavailable")
	}
	index := filepath.Join(real, "index.html")
	info, err := os.Stat(index)
	if err != nil || !info.Mode().IsRegular() {
		return nil, errors.New("web spa: index is unavailable")
	}
	return &webSPAHandler{root: real, index: index}, nil
}

func (h *webSPAHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		webWriteProblem(w, cpErrMethodNotAllowed)
		return
	}
	rel := strings.TrimPrefix(filepath.Clean("/"+r.URL.Path), string(filepath.Separator))
	target := filepath.Join(h.root, rel)
	if real, err := filepath.EvalSymlinks(target); err == nil {
		within, relErr := filepath.Rel(h.root, real)
		if relErr == nil && within != ".." && !strings.HasPrefix(within, ".."+string(filepath.Separator)) {
			if info, statErr := os.Stat(real); statErr == nil && info.Mode().IsRegular() {
				if strings.HasPrefix(rel, "assets/") {
					w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
				}
				http.ServeFile(w, r, real)
				return
			}
		}
	}
	w.Header().Set("Cache-Control", "no-cache")
	http.ServeFile(w, r, h.index)
}
