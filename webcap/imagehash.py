"""
Perceptual image hashing library

Example:

>>> from PIL import Image
>>> hash = phash(Image.open('test.png'))
>>> print(hash)
d879f8f89b1bbf
"""

import numpy
from PIL import Image

try:
    ANTIALIAS = Image.Resampling.LANCZOS
except AttributeError:
    # deprecated in pillow 10
    # https://pillow.readthedocs.io/en/stable/deprecations.html
    ANTIALIAS = Image.ANTIALIAS

"""
You may copy this file, if you keep the copyright information below:


Copyright (c) 2013-2022, Johannes Buchner
https://github.com/JohannesBuchner/imagehash

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.

Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""


def _binary_array_to_hex(arr):
    """
    internal function to make a hex string out of a binary array.
    """
    bit_string = "".join(str(b) for b in 1 * arr.flatten())
    width = int(numpy.ceil(len(bit_string) / 4))
    return "{:0>{width}x}".format(int(bit_string, 2), width=width)


class ImageHash:
    """
    Hash encapsulation. Can be used for dictionary keys and comparisons.
    """

    def __init__(self, binary_array):
        self.hash = binary_array

    def __str__(self):
        return _binary_array_to_hex(self.hash.flatten())

    def __repr__(self):
        return repr(self.hash)

    def __sub__(self, other):
        if other is None:
            raise TypeError("Other hash must not be None.")
        if self.hash.size != other.hash.size:
            raise TypeError("ImageHashes must be of the same shape.", self.hash.shape, other.hash.shape)
        return numpy.count_nonzero(self.hash.flatten() != other.hash.flatten())

    def __eq__(self, other):
        if other is None:
            return False
        return numpy.array_equal(self.hash.flatten(), other.hash.flatten())


def phash(image, hash_size=8, highfreq_factor=4):
    """
    Perceptual Hash computation.

    Implementation follows https://www.hackerfactor.com/blog/index.php?/archives/432-Looks-Like-It.html

    @image must be a PIL instance.
    """
    if hash_size < 2:
        raise ValueError("Hash size must be greater than or equal to 2")

    img_size = hash_size * highfreq_factor
    image = image.convert("L").resize((img_size, img_size), ANTIALIAS)
    pixels = numpy.asarray(image)

    # Replace scipy's DCT with numpy's FFT implementation
    # DCT can be computed using FFT by properly extending and transforming the input
    def dct2d(a):
        # Extend the input array with mirror reflection and compute FFT
        M, N = a.shape
        y = numpy.zeros((2 * M, 2 * N))
        y[:M, :N] = a
        y[M:, :N] = a[::-1, :]  # Mirror vertically
        y[:, N:] = y[:, :N][:, ::-1]  # Mirror horizontally

        # Compute 2D FFT and extract real component
        Y = numpy.fft.rfft2(y)[:M, :N]
        # Apply DCT scaling factors
        scale = numpy.ones((M, N))
        scale[0, :] = numpy.sqrt(1 / 4)
        scale[:, 0] = scale[0, :]
        scale[0, 0] = 1 / 4
        return 2 * numpy.real(Y) * scale

    dct = dct2d(pixels)
    dctlowfreq = dct[:hash_size, :hash_size]
    med = numpy.median(dctlowfreq)
    diff = dctlowfreq > med
    return ImageHash(diff)
