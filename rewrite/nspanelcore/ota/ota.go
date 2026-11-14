// Package ota is a 1:1 Go port of firmware_store.py + the manager OTA-cache
// paths that caused the v1.3.43 upload-500 (async refresh scheduled in the
// executor, leaving _ota_md5 a coroutine; every later upload crashed on
// cache write).
//
// Rules enforced here:
//   - Version compare is zero-padded ("1.0" == "1.0.0", not newer).
//   - Downloads stage to <target>.staging and atomically rename into place;
//     a failed mid-set download never leaves half-overwritten live bytes.
//   - Overlay activation is hash-verified (existence alone re-activated
//     truncated overlays on every boot).
//   - Manual uploads pin EXACT bytes over any overlay shadow copy.
package ota

import (
	"crypto/md5"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// ServableFiles mirrors SERVABLE_FILES: keys are "<kind>/<name>".
var ServableFiles = []string{
	"firmware/sonoff/firmware.bin",
	"firmware/sonoff/data_file.bin",
	"firmware/custom/firmware.bin",
	"firmware/custom/data_file.bin",
	"tft/gui.tft",
	"tft/gui_us.tft",
}

// VersionTuple mirrors _version_tuple: numeric parts, zero-padded to 3.
func VersionTuple(v string) [3]int {
	var out [3]int
	parts := strings.Split(strings.TrimSpace(v), ".")
	for i := 0; i < 3 && i < len(parts); i++ {
		n, err := strconv.Atoi(strings.TrimSpace(parts[i]))
		if err != nil {
			n = 0
		}
		out[i] = n
	}
	return out
}

// IsNewer mirrors is_newer.
func IsNewer(candidate, current string) bool {
	a, b := VersionTuple(candidate), VersionTuple(current)
	return a[0] > b[0] || (a[0] == b[0] && (a[1] > b[1] || (a[1] == b[1] && a[2] > b[2])))
}

// MD5File hashes a file in 64KB chunks (matches _hash_ota_files chunk size).
func MD5File(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := md5.New()
	if _, err := io.CopyBuffer(h, f, make([]byte, 65536)); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// HashBytes is the in-memory equivalent (for tests).
func HashBytes(b []byte) string {
	h := md5.Sum(b)
	return hex.EncodeToString(h[:])
}

// OverlayDir mirrors overlay_dir: <cfg>/.storage/nspanel_core/firmware/<version>.
func OverlayDir(hassConfigPath, version string) string {
	return filepath.Join(hassConfigPath, ".storage", "nspanel_core", "firmware", version)
}

// FlattenedName mirrors key.replace("/", "__").
func FlattenedName(key string) string {
	return strings.ReplaceAll(key, "/", "__")
}

// HashAll hashes every servable key through resolve (bundled vs overlay).
// It is SYNCHRONOUS and returns a map — never a future/coroutine. This is the
// v1.3.43 lesson: the cache value must be a plain dict at assignment time.
func HashAll(resolve func(kind, name string) string) map[string]string {
	out := map[string]string{}
	for _, key := range ServableFiles {
		parts := strings.SplitN(key, "/", 2)
		path := resolve(parts[0], parts[1])
		if path == "" {
			out[key] = ""
			continue
		}
		digest, err := MD5File(path)
		if err != nil {
			out[key] = ""
			continue
		}
		out[key] = digest
	}
	return out
}

// ValidateOverlay verifies overlay files exist and — when expected MD5s are
// supplied (manifest) — still match. Mirrors validate_manifest_against.
func ValidateOverlay(paths map[string]string, expected map[string]string) bool {
	for key, path := range paths {
		fi, err := os.Stat(path)
		if err != nil || fi.IsDir() {
			return false
		}
		want := strings.ToLower(expected[key])
		if want == "" {
			continue
		}
		got, err := MD5File(path)
		if err != nil || got != want {
			return false
		}
	}
	return true
}

// StageAndActivate atomically swaps a verified staging dir into the live
// overlay dir. staging must already contain flattened files. Mirrors the
// _download() tail (_rmtree(target); os.rename(staging, target)).
func StageAndActivate(staging, target string) (map[string]string, error) {
	// Verify all flattened files present before swapping.
	for _, key := range ServableFiles {
		if _, err := os.Stat(filepath.Join(staging, FlattenedName(key))); err != nil {
			return nil, fmt.Errorf("%s: missing from staging: %w", key, err)
		}
	}
	if err := os.RemoveAll(target); err != nil {
		return nil, err
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		return nil, err
	}
	if err := os.Rename(staging, target); err != nil {
		return nil, err
	}
	final := map[string]string{}
	for _, key := range ServableFiles {
		final[key] = filepath.Join(target, FlattenedName(key))
	}
	return final, nil
}

// Proof mirrors the served-file proof dict from note_custom_file.
type Proof struct {
	Name       string `json:"name"`
	MD5        string `json:"md5"`
	Size       int64  `json:"size"`
	Source     string `json:"source"`
	ServedPath string `json:"served_path"`
}

// PinCustom mirrors manager.note_custom_file: copy the uploaded bundled file
// over any overlay shadow copy, re-hash the SERVED path, return proof.
// kind/name like "tft"/"gui.tft".
func PinCustom(bundledPath, overlayPath, servedPath, label string) (Proof, error) {
	if overlayPath != "" && overlayPath != bundledPath {
		if err := os.MkdirAll(filepath.Dir(overlayPath), 0o755); err != nil {
			return Proof{}, err
		}
		src, err := os.Open(bundledPath)
		if err != nil {
			return Proof{}, err
		}
		defer src.Close()
		dst, err := os.Create(overlayPath)
		if err != nil {
			return Proof{}, err
		}
		if _, err := io.Copy(dst, src); err != nil {
			dst.Close()
			return Proof{}, err
		}
		dst.Close()
	}
	serve := servedPath
	if serve == "" {
		serve = bundledPath
	}
	digest, err := MD5File(serve)
	if err != nil {
		return Proof{}, err
	}
	fi, err := os.Stat(serve)
	if err != nil {
		return Proof{}, err
	}
	return Proof{
		Name:       filepath.Base(bundledPath),
		MD5:        digest,
		Size:       fi.Size(),
		Source:     label,
		ServedPath: serve,
	}, nil
}
