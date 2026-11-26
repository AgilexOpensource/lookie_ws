#pragma once

#include <cstddef>
#include <cstdint>

namespace camera_compress_transport
{

// Lossless RVL for 16-bit depth. Consecutive zeros are run-length coded, and
// the other pixels are stored as zigzag deltas. Output is a sequence of 32-bit
// words, so the compressed size is always a multiple of 4.
class RvlCodec
{
public:
  // Returns the compressed size in bytes, or -1 when output_words is too small.
  static int compress(
    const uint16_t * input,
    uint32_t * output,
    int output_words,
    int num_pixels);

  static bool decompress(
    const uint32_t * input,
    int input_words,
    uint16_t * output,
    int num_pixels);

private:
  static bool encodeVle(
    uint32_t value,
    uint32_t *& cursor,
    uint32_t * end,
    uint32_t & word,
    int & nibbles);

  static bool decodeVle(
    const uint32_t *& cursor,
    const uint32_t * end,
    uint32_t & word,
    int & nibbles,
    uint32_t & value);
};

inline bool RvlCodec::encodeVle(
  uint32_t value,
  uint32_t *& cursor,
  uint32_t * end,
  uint32_t & word,
  int & nibbles)
{
  do {
    uint32_t nibble = value & 0x7u;
    value >>= 3;
    if (value != 0) {
      nibble |= 0x8u;
    }
    word = (word << 4) | nibble;
    if (++nibbles == 8) {
      if (cursor >= end) {
        return false;
      }
      *cursor++ = word;
      nibbles = 0;
      word = 0;
    }
  } while (value != 0);
  return true;
}

inline bool RvlCodec::decodeVle(
  const uint32_t *& cursor,
  const uint32_t * end,
  uint32_t & word,
  int & nibbles,
  uint32_t & value)
{
  value = 0;
  int bits = 29;
  uint32_t nibble = 0;
  int guard = 0;
  do {
    if (nibbles == 0) {
      if (cursor >= end) {
        return false;
      }
      word = *cursor++;
      nibbles = 8;
    }
    nibble = word & 0xf0000000u;
    if (bits < 0) {
      return false;
    }
    value |= (nibble << 1) >> bits;
    word <<= 4;
    --nibbles;
    bits -= 3;
    if (++guard > 11) {
      return false;
    }
  } while ((nibble & 0x80000000u) != 0);
  return true;
}

inline int RvlCodec::compress(
  const uint16_t * input,
  uint32_t * output,
  int output_words,
  int num_pixels)
{
  if (num_pixels == 0) {
    return 0;
  }
  if (input == nullptr || output == nullptr || num_pixels < 0 || output_words < 1) {
    return -1;
  }

  uint32_t * cursor = output;
  uint32_t * end = output + output_words;
  uint32_t word = 0;
  int nibbles = 0;
  uint16_t previous = 0;

  for (int i = 0; i < num_pixels;) {
    int zeros = 0;
    for (; i < num_pixels && input[i] == 0; ++i, ++zeros) {
    }
    if (!encodeVle(static_cast<uint32_t>(zeros), cursor, end, word, nibbles)) {
      return -1;
    }

    const int run_start = i;
    int nonzeros = 0;
    for (; i < num_pixels && input[i] != 0; ++i, ++nonzeros) {
    }
    if (!encodeVle(static_cast<uint32_t>(nonzeros), cursor, end, word, nibbles)) {
      return -1;
    }

    for (int j = 0; j < nonzeros; ++j) {
      const int delta = static_cast<int>(input[run_start + j]) - static_cast<int>(previous);
      const uint32_t positive = static_cast<uint32_t>((delta << 1) ^ (delta >> 31));
      if (!encodeVle(positive, cursor, end, word, nibbles)) {
        return -1;
      }
      previous = input[run_start + j];
    }
  }

  if (nibbles != 0) {
    if (cursor >= end) {
      return -1;
    }
    *cursor++ = word << (4 * (8 - nibbles));
  }
  return static_cast<int>((cursor - output) * static_cast<int>(sizeof(uint32_t)));
}

inline bool RvlCodec::decompress(
  const uint32_t * input,
  int input_words,
  uint16_t * output,
  int num_pixels)
{
  if (num_pixels == 0) {
    return true;
  }
  if (input == nullptr || output == nullptr || num_pixels < 0 || input_words < 0) {
    return false;
  }

  const uint32_t * cursor = input;
  const uint32_t * end = input + input_words;
  uint32_t word = 0;
  int nibbles = 0;
  uint16_t previous = 0;
  int remaining = num_pixels;

  while (remaining > 0) {
    uint32_t zeros_u = 0;
    uint32_t nonzeros_u = 0;
    if (!decodeVle(cursor, end, word, nibbles, zeros_u)) {
      return false;
    }
    if (zeros_u > static_cast<uint32_t>(remaining)) {
      return false;
    }
    const int zeros = static_cast<int>(zeros_u);
    remaining -= zeros;
    for (int i = 0; i < zeros; ++i) {
      *output++ = 0;
    }

    if (!decodeVle(cursor, end, word, nibbles, nonzeros_u)) {
      return false;
    }
    if (nonzeros_u > static_cast<uint32_t>(remaining)) {
      return false;
    }
    const int nonzeros = static_cast<int>(nonzeros_u);
    remaining -= nonzeros;
    for (int i = 0; i < nonzeros; ++i) {
      uint32_t positive_u = 0;
      if (!decodeVle(cursor, end, word, nibbles, positive_u)) {
        return false;
      }
      const int positive = static_cast<int>(positive_u);
      const int delta = (positive >> 1) ^ -(positive & 1);
      const int current = static_cast<int>(previous) + delta;
      const auto stored = static_cast<uint16_t>(current);
      *output++ = stored;
      previous = stored;
    }
  }
  return true;
}

}  // namespace camera_compress_transport
