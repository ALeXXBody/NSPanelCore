package pcode_test

import (
	"bytes"
	"testing"

	"nspanelcore/pcode"
)

func TestVarintRoundTrip(t *testing.T) {
	for _, v := range []uint64{0, 1, 127, 128, 300, 1 << 32, 1<<64 - 1} {
		enc := pcode.EncodeVarint(v)
		r := pcode.NewReader(enc)
		got, err := r.ReadVarint()
		if err != nil || got != v {
			t.Fatalf("varint %d -> %d, err=%v", v, got, err)
		}
	}
}

func TestZeroOmission(t *testing.T) {
	if len(pcode.EncodeVarintField(1, 0)) != 0 {
		t.Fatal("zero varint must be omitted")
	}
	if len(pcode.EncodeBoolField(2, false)) != 0 {
		t.Fatal("false bool must be omitted")
	}
	if len(pcode.EncodeStringField(3, "")) != 0 {
		t.Fatal("empty string must be omitted")
	}
	if len(pcode.EncodeBytesField(4, nil)) != 0 {
		t.Fatal("empty bytes must be omitted")
	}
	if len(pcode.EncodeFloatField(5, 0)) != 0 {
		t.Fatal("zero float must be omitted")
	}
	if len(pcode.EncodePackedInt32Field(6, nil)) != 0 {
		t.Fatal("empty packed must be omitted")
	}
	// Nested messages always emit, even when empty.
	if len(pcode.EncodeMessageField(7, nil)) != 2 {
		t.Fatalf("empty nested message must still emit tag+len, got %d bytes", len(pcode.EncodeMessageField(7, nil)))
	}
}

func TestStringFieldRoundTrip(t *testing.T) {
	enc := pcode.EncodeStringField(2, "Kitchen")
	r := pcode.NewReader(enc)
	fn, wt, err := r.ReadTag()
	if err != nil || fn != 2 || wt != 2 {
		t.Fatalf("tag = %d/%d err=%v", fn, wt, err)
	}
	b, err := r.ReadBytes()
	if err != nil || !bytes.Equal(b, []byte("Kitchen")) {
		t.Fatalf("payload = %q err=%v", b, err)
	}
}

func TestFloatRoundTrip(t *testing.T) {
	enc := pcode.EncodeFloatField(1, 21.5)
	r := pcode.NewReader(enc)
	fn, wt, err := r.ReadTag()
	if err != nil || fn != 1 || wt != 5 {
		t.Fatalf("tag = %d/%d err=%v", fn, wt, err)
	}
	f, err := r.ReadFloat()
	if err != nil || f != 21.5 {
		t.Fatalf("float = %v err=%v", f, err)
	}
}

func TestTruncatedErrors(t *testing.T) {
	if _, err := pcode.NewReader([]byte{0x80}).ReadVarint(); err == nil {
		t.Fatal("expected truncated varint error")
	}
	if _, err := pcode.NewReader([]byte{0x05}).ReadBytes(); err == nil {
		t.Fatal("expected truncated field error")
	}
	if _, err := pcode.NewReader([]byte{0x01, 0x02}).ReadFloat(); err == nil {
		t.Fatal("expected truncated float error")
	}
}

func TestZigzag(t *testing.T) {
	if pcode.ZigzagDecode(0) != 0 || pcode.ZigzagDecode(1) != -1 || pcode.ZigzagDecode(2) != 1 {
		t.Fatal("zigzag decode wrong")
	}
	if pcode.ZigzagEncode(-1) != 1 || pcode.ZigzagEncode(1) != 2 {
		t.Fatal("zigzag encode wrong")
	}
}

func TestBase64(t *testing.T) {
	if pcode.ToBase64([]byte("hi")) != "aGk=" {
		t.Fatal("base64 wrong")
	}
}
