// Package pcode is a 1:1 Go port of panel_pb/codec.py.
//
// Minimal protobuf wire-format codec for the panel protocol. Zero external
// dependencies. Wire rules (proto3): field key = (field_number << 3) |
// wire_type; wire types 0=varint, 2=length-delimited, 5=32-bit; zero-valued
// scalars are omitted on encode exactly like generated proto3 serializers.
package pcode

import (
	"encoding/base64"
	"encoding/binary"
	"errors"
	"math"
)

// EncodeVarint encodes a uint64 as protobuf varint.
func EncodeVarint(v uint64) []byte {
	var out []byte
	for {
		b := byte(v & 0x7F)
		v >>= 7
		if v != 0 {
			out = append(out, b|0x80)
		} else {
			out = append(out, b)
			return out
		}
	}
}

// EncodeTag encodes field key = (field_number << 3) | wire_type.
func EncodeTag(field int, wireType int) []byte {
	return EncodeVarint(uint64(field<<3 | wireType))
}

// EncodeVarintField omits zero exactly like proto3.
func EncodeVarintField(field int, v int64) []byte {
	if v == 0 {
		return nil
	}
	out := EncodeTag(field, 0)
	return append(out, EncodeVarint(uint64(v))...)
}

// EncodeBoolField omits false exactly like proto3.
func EncodeBoolField(field int, v bool) []byte {
	if !v {
		return nil
	}
	return EncodeVarintField(field, 1)
}

// EncodeStringField omits empty exactly like proto3.
func EncodeStringField(field int, s string) []byte {
	if s == "" {
		return nil
	}
	data := []byte(s)
	out := EncodeTag(field, 2)
	out = append(out, EncodeVarint(uint64(len(data)))...)
	return append(out, data...)
}

// EncodeBytesField omits empty exactly like proto3.
func EncodeBytesField(field int, b []byte) []byte {
	if len(b) == 0 {
		return nil
	}
	out := EncodeTag(field, 2)
	out = append(out, EncodeVarint(uint64(len(b)))...)
	return append(out, b...)
}

// EncodeMessageField always emits, even when empty (nested messages).
func EncodeMessageField(field int, b []byte) []byte {
	out := EncodeTag(field, 2)
	out = append(out, EncodeVarint(uint64(len(b)))...)
	return append(out, b...)
}

// EncodeFloatField omits zero exactly like proto3 (32-bit little-endian).
func EncodeFloatField(field int, f float32) []byte {
	if f == 0 {
		return nil
	}
	out := EncodeTag(field, 5)
	var buf [4]byte
	binary.LittleEndian.PutUint32(buf[:], math.Float32bits(f))
	return append(out, buf[:]...)
}

// EncodePackedInt32Field omits empty; payload is concatenated varints.
func EncodePackedInt32Field(field int, vals []int32) []byte {
	if len(vals) == 0 {
		return nil
	}
	var payload []byte
	for _, v := range vals {
		payload = append(payload, EncodeVarint(uint64(int64(v)))...)
	}
	out := EncodeTag(field, 2)
	out = append(out, EncodeVarint(uint64(len(payload)))...)
	return append(out, payload...)
}

// ToBase64 mirrors message_to_base64.
func ToBase64(b []byte) string {
	return base64.StdEncoding.EncodeToString(b)
}

// Reader mirrors codec.Reader with identical error semantics.
type Reader struct {
	Data []byte
	Pos  int
}

func NewReader(data []byte) *Reader { return &Reader{Data: data} }

func (r *Reader) EOF() bool { return r.Pos >= len(r.Data) }

var (
	ErrTruncatedVarint = errors.New("truncated varint")
	ErrVarintTooLong   = errors.New("varint too long")
	ErrTruncatedField  = errors.New("truncated length-delimited field")
	ErrTruncatedFloat  = errors.New("truncated float")
)

// ReadVarint mirrors read_varint (shift > 70 guard).
func (r *Reader) ReadVarint() (uint64, error) {
	var result uint64
	var shift uint
	for {
		if r.Pos >= len(r.Data) {
			return 0, ErrTruncatedVarint
		}
		b := r.Data[r.Pos]
		r.Pos++
		result |= uint64(b&0x7F) << shift
		if b&0x80 == 0 {
			return result, nil
		}
		shift += 7
		if shift > 70 {
			return 0, ErrVarintTooLong
		}
	}
}

// ReadBytes mirrors read_bytes.
func (r *Reader) ReadBytes() ([]byte, error) {
	n, err := r.ReadVarint()
	if err != nil {
		return nil, err
	}
	if uint64(len(r.Data)-r.Pos) < n {
		return nil, ErrTruncatedField
	}
	out := r.Data[r.Pos : r.Pos+int(n)]
	r.Pos += int(n)
	return out, nil
}

// ReadFloat mirrors read_float (little-endian 32-bit).
func (r *Reader) ReadFloat() (float32, error) {
	if len(r.Data)-r.Pos < 4 {
		return 0, ErrTruncatedFloat
	}
	bits := binary.LittleEndian.Uint32(r.Data[r.Pos : r.Pos+4])
	r.Pos += 4
	return math.Float32frombits(bits), nil
}

// ReadTag mirrors read_tag.
func (r *Reader) ReadTag() (int, int, error) {
	key, err := r.ReadVarint()
	if err != nil {
		return 0, 0, err
	}
	return int(key >> 3), int(key & 7), nil
}

// ZigzagDecode mirrors zigzag_decode.
func ZigzagDecode(v uint64) int64 {
	return int64(v>>1) ^ -int64(v&1)
}

// ZigzagEncode mirrors zigzag_encode (for negative-aware int32/int64).
func ZigzagEncode(v int64) uint64 {
	if v < 0 {
		return uint64(v<<1) ^ uint64(v>>63)
	}
	return uint64(v << 1)
}
