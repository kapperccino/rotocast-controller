# Desktop stand-in for MicroPython's framebuf, just enough for rotocast_ui.
# Mirrors framebuf.c: RGB565 is stored native little-endian, MONO_HLSB
# packs 8 pixels per byte MSB first, blit maps source pixels through the
# palette and skips any that equal key after mapping.

RGB565 = 1
MONO_HLSB = 3


class FrameBuffer:
    def __init__(self, buf, width, height, fmt, stride=None):
        self.buf = buf
        self.w = width
        self.h = height
        self.fmt = fmt
        self.stride = width if stride is None else stride

    def pixel(self, x, y, c=None):
        if not (0 <= x < self.w and 0 <= y < self.h):
            return None

        if self.fmt == RGB565:
            i = (y * self.stride + x) * 2
            if c is None:
                return self.buf[i] | (self.buf[i + 1] << 8)
            self.buf[i] = c & 0xFF
            self.buf[i + 1] = (c >> 8) & 0xFF
        else:
            bpr = (self.stride + 7) // 8
            i = y * bpr + x // 8
            bit = 0x80 >> (x % 8)
            if c is None:
                return 1 if self.buf[i] & bit else 0
            if c:
                self.buf[i] |= bit
            else:
                self.buf[i] &= ~bit & 0xFF

    def fill(self, c):
        self.fill_rect(0, 0, self.w, self.h, c)

    def fill_rect(self, x, y, w, h, c):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                self.pixel(xx, yy, c)

    def blit(self, src, x, y, key=-1, palette=None):
        for sy in range(src.h):
            for sx in range(src.w):
                col = src.pixel(sx, sy)
                if palette is not None:
                    col = palette.pixel(col, 0)
                if col != key:
                    self.pixel(x + sx, y + sy, col)
