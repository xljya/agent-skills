#include <stdint.h>
#include <stddef.h>
static uint32_t mix(uint32_t z, uint32_t y, uint32_t sum, uint32_t key) {
    return ((z >> 5 ^ y << 2) + (y >> 3 ^ z << 4)) ^ ((sum ^ y) + (key ^ z));
}
__declspec(dllexport) void block(uint32_t *data, int length, const uint32_t *key) {
    uint32_t delta = 0x9e3779b9, sum = (6 + 52 / length) * delta, y = data[0];
    while (sum != 0) {
        uint32_t selector = (sum >> 2) & 3;
        for (int i = length - 1; i > 0; i--) {
            y = data[i] -= mix(data[i-1], y, sum, key[(i & 3) ^ selector]);
        }
        y = data[0] -= mix(data[length-1], y, sum, key[selector]);
        sum -= delta;
    }
}
