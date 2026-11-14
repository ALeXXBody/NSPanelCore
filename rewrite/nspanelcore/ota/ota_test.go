package ota_test

import (
	"os"
	"path/filepath"
	"testing"

	"nspanelcore/ota"
)

func TestVersionCompare(t *testing.T) {
	if !ota.IsNewer("0.1.169", "0.1.168") {
		t.Fatal("should be newer")
	}
	if ota.IsNewer("1.0", "1.0.0") {
		t.Fatal("1.0 == 1.0.0, not newer (zero-pad rule)")
	}
	if ota.IsNewer("1.3.42", "1.3.43") {
		t.Fatal("older must not be newer")
	}
	if !ota.IsNewer("1.3.43", "1.3.42") {
		t.Fatal("patch bump must be newer")
	}
}

func TestHashAllIsSyncMap(t *testing.T) {
	// v1.3.43 regression: the cache value must be a plain map, never a
	// future/coroutine. HashAll returns the map directly.
	dir := t.TempDir()
	p := filepath.Join(dir, "gui.tft")
	os.WriteFile(p, []byte("blank-tft-bytes"), 0o644)
	got := ota.HashAll(func(kind, name string) string {
		if kind == "tft" && name == "gui.tft" {
			return p
		}
		return ""
	})
	if got["tft/gui.tft"] != ota.HashBytes([]byte("blank-tft-bytes")) {
		t.Fatalf("bad hash: %v", got)
	}
	if got["tft/gui_us.tft"] != "" {
		t.Fatal("missing file must hash to empty")
	}
	// The crash was item assignment on a non-map; assignment must work.
	got["tft/gui.tft"] = "x"
}

func TestStageAndActivateAtomic(t *testing.T) {
	base := t.TempDir()
	staging := filepath.Join(base, "v.staging")
	target := filepath.Join(base, ".storage", "nspanel_core", "firmware", "9.9.9")
	os.MkdirAll(staging, 0o755)
	for _, k := range ota.ServableFiles {
		os.WriteFile(filepath.Join(staging, ota.FlattenedName(k)), []byte("x:"+k), 0o644)
	}
	final, err := ota.StageAndActivate(staging, target)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(target); err != nil {
		t.Fatal("target missing after activate")
	}
	if _, err := os.Stat(staging); !os.IsNotExist(err) {
		t.Fatal("staging must be gone after rename")
	}
	if len(final) != len(ota.ServableFiles) {
		t.Fatal("final map incomplete")
	}
}

func TestPinCustomOverwritesShadow(t *testing.T) {
	dir := t.TempDir()
	bundled := filepath.Join(dir, "gui.tft")
	overlay := filepath.Join(dir, "overlay", "tft__gui.tft")
	os.WriteFile(bundled, []byte("exact-upload-bytes"), 0o644)
	os.MkdirAll(filepath.Dir(overlay), 0o755)
	os.WriteFile(overlay, []byte("stale-release-bytes"), 0o644)
	proof, err := ota.PinCustom(bundled, overlay, overlay, "manual upload")
	if err != nil {
		t.Fatal(err)
	}
	shadow, _ := os.ReadFile(overlay)
	if string(shadow) != "exact-upload-bytes" {
		t.Fatalf("shadow not overwritten: %q", shadow)
	}
	if proof.MD5 != ota.HashBytes([]byte("exact-upload-bytes")) {
		t.Fatal("proof hash wrong")
	}
}
