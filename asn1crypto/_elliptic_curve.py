# coding: utf-8

"""
The following source code is derived from
http://webpages.charter.net/curryfans/peter/downloads.html, but has been heavily
modified to fit into this projects lint settings, and to support loading and
serializing to/from ECPrimePoint format. The original project license is listed
below:

Copyright (c) 2014 Peter Pearson

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

from __future__ import unicode_literals
from __future__ import division

import sys
import math
from ctypes.util import find_library
from ctypes import CDLL, c_int, c_char_p, c_void_p, create_string_buffer

from ._int_conversion import int_to_bytes, int_from_bytes

if sys.version_info < (3,):
    byte_cls = str
    int_types = (int, long)  #pylint: disable=E0602

else:
    byte_cls = bytes
    int_types = int



class PrimeCurve():
    """
    Elliptic curve over a prime field. Characteristic two field curves are not
    supported.
    """

    def __init__(self, p, a, b):
        """
        The curve of points satisfying y^2 = x^3 + a*x + b (mod p)

        :param p:
            The prime number as an integer

        :param a:
            The component a as an integer

        :param b:
            The component b as an integer
        """

        self.p = p
        self.a = a
        self.b = b

    def contains(self, point):
        """
        :param point:
            A Point object

        :return:
            Boolean if the point is on this curve
        """

        y2 = point.y * point.y
        x3 = point.x * point.x * point.x
        return (y2 - (x3 + self.a * point.x + self.b)) % self.p == 0


class PrimePoint():
    """
    A point on a prime-field elliptic curve
    """

    @classmethod
    def load(cls, curve, data):
        """
        Loads a Point from the ECPoint OctetString representation

        :param curve:
            A PrimeCurve object of the curve the point is on

        :param data:
            A byte string of the ECPoint representation of the point. This
            representation uses the first byte as a compression indicator, and
            then lists the X and Y as base256 byte string integers

        :return:
            A PrimePoint object
        """

        first_byte = data[0:1]

        # Uncompressed
        if first_byte == b'\x04':
            remaining = data[1:]
            field_len = len(remaining) // 2
            x = int_from_bytes(remaining[0:field_len])
            y = int_from_bytes(remaining[field_len:])
            return cls(curve, x, y)

        if first_byte not in (b'\x02', b'\x03'):
            raise ValueError('Invalid ECPoint representation of a point - first byte is incorrect')

        raise ValueError('Compressed ECPoint representations are not supported')

    def __init__(self, curve, x, y, order=None):
        """
        :param curve:
            A PrimeCurve object

        :param x:
            The x coordinate of the point as an integer

        :param y:
            The y coordinate of the point as an integer

        :param order:
            The order of the point, as an integer - optional
        """

        self.curve = curve
        self.x = x
        self.y = y
        self.order = order

        # self.curve is allowed to be None only for INFINITY:
        if self.curve:
            assert self.curve.contains(self)

        if self.order:
            assert self * self.order == INFINITY

    def __cmp__(self, other):
        """
        :param other:
            A PrimePoint object

        :return:
            0 if identical, 1 otherwise
        """
        if self.curve == other.curve and self.x == other.x and self.y == other.y:
            return 0
        else:
            return 1

    def __add__(self, other):
        """
        :param other:
            A PrimePoint object

        :return:
            A PrimePoint object
        """

        # X9.62 B.3:

        if other == INFINITY:
            return self
        if self == INFINITY:
            return other
        assert self.curve == other.curve
        if self.x == other.x:
            if (self.y + other.y) % self.curve.p == 0:
                return INFINITY
            else:
                return self.double()

        p = self.curve.p

        l = ((other.y - self.y) * inverse_mod(other.x - self.x, p)) % p

        x3 = (l * l - self.x - other.x) % p
        y3 = (l * (self.x - x3) - self.y) % p

        return PrimePoint(self.curve, x3, y3)

    def __mul__(self, other):
        """
        :param other:
            An integer to multiple the Point by

        :return:
            A PrimePoint object
        """

        def leftmost_bit(x):
            assert x > 0
            result = 1
            while result <= x:
                result = 2 * result
            return result // 2

        e = other
        if self.order:
            e = e % self.order
        if e == 0:
            return INFINITY
        if self == INFINITY:
            return INFINITY
        assert e > 0

        # From X9.62 D.3.2:

        e3 = 3 * e
        negative_self = PrimePoint(self.curve, self.x, -self.y, self.order)
        i = leftmost_bit(e3) // 2
        result = self
        # print "Multiplying %s by %d (e3 = %d):" % ( self, other, e3 )
        while i > 1:
            result = result.double()
            if (e3 & i) != 0 and (e & i) == 0:
                result = result + self
            if (e3 & i) == 0 and (e & i) != 0:
                result = result + negative_self
            # print ". . . i = %d, result = %s" % ( i, result )
            i = i // 2

        return result

    def __rmul__(self, other):
        """
        :param other:
            An integer to multiple the Point by

        :return:
            A PrimePoint object
        """

        return self * other

    def double(self):
        """
        :return:
            A PrimePoint object that is twice this point
        """

        # X9.62 B.3:

        p = self.curve.p
        a = self.curve.a

        l = ((3 * self.x * self.x + a) * inverse_mod(2 * self.y, p)) % p

        x3 = (l * l - 2 * self.x) % p
        y3 = (l * (self.x - x3) - self.y) % p

        return PrimePoint(self.curve, x3, y3)

    def dump(self):
        """
        Dumps a PrimePoint to the ECPoint OctetString representation

        :return:
            A byte string of the ECPoint representation
        """

        field_len = int(math.ceil(math.log(self.curve.p, 2) / 8))

        xb = int_to_bytes(self.x)
        yb = int_to_bytes(self.y)

        # Make sure the fields are full width, according to the spec
        while len(xb) < field_len:
            xb = b'\x00' + xb
        while len(yb) < field_len:
            yb = b'\x00' + yb

        return b'\x04' + xb + yb


# This one point is the Point At Infinity for all purposes:
INFINITY = PrimePoint(None, None, None)


# NIST Curve P-192:
NIST_192_CURVE = PrimeCurve(
    6277101735386680763835789423207666416083908700390324961279,
    -3,
    0x64210519e59c80e70fa7e9ab72243049feb8deecc146b9b1
)
NIST_P192_BASE_POINT = PrimePoint(
    NIST_192_CURVE,
    0x188da80eb03090f67cbf20eb43a18800f4ff0afd82ff1012,
    0x07192b95ffc8da78631011ed6b24cdd573f977a11e794811,
    6277101735386680763835789423176059013767194773182842284081
)


# NIST Curve P-224:
NIST_P224_CURVE = PrimeCurve(
    26959946667150639794667015087019630673557916260026308143510066298881,
    -3,
    0xb4050a850c04b3abf54132565044b0b7d7bfd8ba270b39432355ffb4
)
NIST_P224_BASE_POINT = PrimePoint(
    NIST_P224_CURVE,
    0xb70e0cbd6bb4bf7f321390b94a03c1d356c21122343280d6115c1d21,
    0xbd376388b5f723fb4c22dfe6cd4375a05a07476444d5819985007e34,
    26959946667150639794667015087019625940457807714424391721682722368061
)


# NIST Curve P-256:
NIST_P256_CURVE = PrimeCurve(
    115792089210356248762697446949407573530086143415290314195533631308867097853951,
    -3,
    0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
)
NIST_P256_BASE_POINT = PrimePoint(
    NIST_P256_CURVE,
    0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
    0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5,
    115792089210356248762697446949407573529996955224135760342422259061068512044369
)


# NIST Curve P-384:
NIST_P384_CURVE = PrimeCurve(
    39402006196394479212279040100143613805079739270465446667948293404245721771496870329047266088258938001861606973112319,
    -3,
    0xb3312fa7e23ee7e4988e056be3f82d19181d9c6efe8141120314088f5013875ac656398d8a2ed19d2a85c8edd3ec2aef
)
NIST_P384_BASE_POINT = PrimePoint(
    NIST_P384_CURVE,
    0xaa87ca22be8b05378eb1c71ef320ad746e1d3b628ba79b9859f741e082542a385502f25dbf55296c3a545e3872760ab7,
    0x3617de4a96262c6f5d9e98bf9292dc29f8f41dbd289a147ce9da3113b5f0b8c00a60b1ce1d7e819d7a431d7c90ea0e5f,
    39402006196394479212279040100143613805079739270465446667946905279627659399113263569398956308152294913554433653942643
)


# NIST Curve P-521:
NIST_P521_CURVE = PrimeCurve(
    6864797660130609714981900799081393217269435300143305409394463459185543183397656052122559640661454554977296311391480858037121987999716643812574028291115057151,
    -3,
    0x051953eb9618e1c9a1f929a21a0b68540eea2da725b99b315f3b8b489918ef109e156193951ec7e937b1652c0bd3bb1bf073573df883d2c34f1ef451fd46b503f00
)
NIST_P521_BASE_POINT = PrimePoint(
    NIST_P521_CURVE,
    0xc6858e06b70404e9cd9e3ecb662395b4429c648139053fb521f828af606b4d3dbaa14b5e77efe75928fe1dc127a2ffa8de3348b3c1856a429bf97e7e31c2e5bd66,
    0x11839296a789a3bc0045c8a5fb42c7d1bd998f54449579b446817afbd17273e662c97ee72995ef42640c550b9013fad0761353c7086a272c24088be94769fd16650,
    6864797660130609714981900799081393217269435300143305409394463459185543183397655394245057746333217197532963996371363321113864768612440380340372808892707005449
)



use_python_inverse_mod = True

libcrypto_path = find_library('libcrypto')
if libcrypto_path:
    try:
        libcrypto = CDLL(libcrypto_path)

        BN_new = libcrypto.BN_new
        BN_new.argtypes = []
        BN_new.restype = c_void_p

        BN_bin2bn = libcrypto.BN_bin2bn
        BN_bin2bn.argtypes = [c_char_p, c_int, c_void_p]
        BN_bin2bn.restype = c_void_p

        BN_bn2bin = libcrypto.BN_bn2bin
        BN_bn2bin.argtypes = [c_void_p, c_char_p]
        BN_bn2bin.restype = c_int

        BN_set_negative = libcrypto.BN_set_negative
        BN_set_negative.argtypes = [c_void_p, c_int]
        BN_set_negative.restype = None

        BN_num_bits = libcrypto.BN_num_bits
        BN_num_bits.argtypes = [c_void_p]
        BN_num_bits.restype = c_int

        BN_free = libcrypto.BN_free
        BN_free.argtypes = [c_void_p]
        BN_free.restype = None

        BN_CTX_new = libcrypto.BN_CTX_new
        BN_CTX_new.argtypes = []
        BN_CTX_new.restype = c_void_p

        BN_CTX_free = libcrypto.BN_CTX_free
        BN_CTX_free.argtypes = [c_void_p]
        BN_CTX_free.restype = None

        BN_mod_inverse = libcrypto.BN_mod_inverse
        BN_mod_inverse.argtypes = [c_void_p, c_void_p, c_void_p, c_void_p]
        BN_mod_inverse.restype = c_void_p

        use_python_inverse_mod = False

    except (AttributeError):  #pylint: disable=W0704
        pass

if not use_python_inverse_mod:

    def inverse_mod(a, p):
        """
        Compute the inverse modul
        """

        ctx = BN_CTX_new()

        a_bytes = int_to_bytes(abs(a))
        p_bytes = int_to_bytes(abs(p))

        a_buf = create_string_buffer(a_bytes)
        a_bn = BN_bin2bn(a_buf, len(a_bytes), None)
        if a < 0:
            BN_set_negative(a_bn, 1)

        p_buf = create_string_buffer(p_bytes)
        p_bn = BN_bin2bn(p_buf, len(p_bytes), None)
        if p < 0:
            BN_set_negative(p_bn, 1)

        r_bn = BN_mod_inverse(None, a_bn, p_bn, ctx)
        r_len_bits = BN_num_bits(r_bn)
        r_len = math.ceil(r_len_bits / 8)
        r_buf = create_string_buffer(r_len)
        BN_bn2bin(r_bn, r_buf)
        result = int_from_bytes(r_buf.raw)

        BN_free(a_bn)
        BN_free(p_bn)
        BN_free(r_bn)
        BN_CTX_free(ctx)

        return result

else:

    def inverse_mod(a, m):
        if a < 0 or m <= a:
            a = a % m

        # From Ferguson and Schneier, roughly:

        c, d = a, m
        uc, vc, ud, vd = 1, 0, 0, 1
        while c != 0:
            q, c, d = divmod(d, c) + (c,)
            uc, vc, ud, vd = ud - q*uc, vd - q*vc, uc, vc

        # At this point, d is the GCD, and ud*a+vd*m = d.
        # If d == 1, this means that ud is a inverse.

        assert d == 1
        if ud > 0:
            return ud
        else:
            return ud + m
