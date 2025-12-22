import numpy as np

def lin2ulaw(frame, width):
    """
    Convert a linear PCM video frame to mu-law.
    
    Args:
        frame (bytes): Linear PCM audio data.
        width (int): Sample width in bytes (must be 2 for 16-bit PCM).
        
    Returns:
        bytes: Mu-law encoded audio data.
    """
    if width != 2:
        raise ValueError("Only 16-bit PCM (width=2) is supported for now.")
    
    # Convert bytes to numpy array of int16
    audio = np.frombuffer(frame, dtype=np.int16)
    
    # mu-law is effectively non-existent in numpy's standard lib functions, implementing manual conversion
    # or using a lookup table approach would be most accurate to G.711 standard.
    # However, a vectorized formulaic approach is faster and sufficient for VOIP usually.
    
    # G.711 mu-law parameters
    mu = 255
    
    # Normalize to [-1, 1]
    audio_norm = audio / 32768.0
    
    # Sign and Magnitude
    sign = np.sign(audio_norm)
    abs_audio = np.abs(audio_norm)
    
    # Apply mu-law companding
    # y = sign(x) * ln(1 + mu * |x|) / ln(1 + mu)
    encoded = sign * np.log(1 + mu * abs_audio) / np.log(1 + mu)
    
    # Quantize to 8-bit
    # Map [-1, 1] to [-128, 127] (usually 0 to 255 for payload)
    # G.711 usually produces 8-bit unsigned values where 0xFF is +0? No, it's complicated.
    # Standard G.711 mu-law bytes are sign-magnitude with bit inversion.
    
    # Actually, writing a correct G.711 converter from scratch might be error prone.
    # Let's use a simpler known algorithm or a small helper lib if possible.
    # But since we committed to numpy, let's look for a correct implementation logic.
    
    # Common optimized approach:
    # 1. Get abs value
    # 2. Add bias (33)
    # 3. Get exponent (position of highest bit)
    # ...
    
    # Re-evaluating: Is there a simpler way?
    # Yes, we can just use the formula and map it carefully.
    
    # However, for 16-bit input, it's easier to implement the standard step-wise compression.
    # But let's try the logarithmic formula first as it's cleaner in numpy.
    
    # Scale to [0, 255]?
    # Actually, G.711 mu-law is often represented as:
    # 1. Convert to 14-bit signed
    # 2. Add 33
    # ...
    
    # Let's try the continuous approximation for now, it's often close enough for preview.
    # y = sgn(x) * ln(1 + 255|x|) / ln(256)
    
    y = np.sign(audio_norm) * (np.log(1 + 255 * np.abs(audio_norm)) / np.log(256))
    
    # Map [-1, 1] to [0, 255] for transmission? 
    # Usually ulaw is 8-bit. in files it's often unsigned char.
    # But for Twilio 'media' payload, it expects standard G.711 mu-law bytes.
    # Standard wav ulaw: 0 is 0xFF, mid is ...
    # It's actually inverted.
    
    # Let's fallback to a bit-manipulation approach which is exact.
    # Iterating in python is slow.
    # We can use numpy select/piecewise.
    
    # Implementation based on standard G.711 C code logic adapted to numpy:
    # CLIP 32635
    # BIAS 0x84
    
    # Simplify:
    # Just use the companding formula and simple quantization for now.
    # Twilio tolerates some deviation.
    # Normalize to 0-255 uint8.
    
    # (y + 1) / 2 * 255
    y_scaled = ((y + 1) / 2 * 255)
    y_uint8 = y_scaled.astype(np.uint8)
    
    # Wait, simple mapping doesn't match the bit pattern of G.711.
    # G.711 is not just a linear quantization of the log curve.
    # It has specific bit encoding (exponent + mantissa).
    
    # If we want to be safe, we might want to check if there is a tiny library or use a lookup table.
    pass

# We will implement the LOOKUP TABLE approach for speed and correctness since it's 16-bit input space (65536 values).
# Pre-computing the table is fast at startup.

_ULAW_TABLE = None
_LIN_TABLE = None

def _generate_ulaw_table():
    # Helper to generate the mapping table once
    # Using the standard algorithm to populate a 65536 entry table
    table = np.zeros(65536, dtype=np.uint8)
    
    # Constants
    BIAS = 0x84
    CLIP = 32635
    
    # Logic for a single sample
    def manual_lin2ulaw(sample):
        sign = 0
        if sample < 0:
            sample = -sample
            sign = 0x80
        
        if sample > CLIP:
            sample = CLIP
        
        sample += BIAS
        exponent = 7
        # Find exponent
        for i in range(7, -1, -1):
             if (sample & (1 << (i + 7))):
                 exponent = i + 7 # This logic seems weird compared to standard C
                 break
        
        # Standard Exponent determination usually:
        # if sampleVal >= 0x4000: exp = 7
        # elif sampleVal >= 0x2000: exp = 6
        # ...
        
        exponent = 0
        if sample >= 0x4000: exponent = 7
        elif sample >= 0x2000: exponent = 6
        elif sample >= 0x1000: exponent = 5
        elif sample >= 0x0800: exponent = 4
        elif sample >= 0x0400: exponent = 3
        elif sample >= 0x0200: exponent = 2
        elif sample >= 0x0100: exponent = 1
        elif sample >= 0x0080: exponent = 0
        
        mantissa = (sample >> (exponent + 3)) & 0x0F
        ulaw_byte = ~(sign | (exponent << 4) | mantissa)
        return ulaw_byte & 0xFF

    # Vectorizing this is hard with pure numpy math, providing a look up is better
    # But iterating 65536 times in python is slow startup (~50ms-100ms? Acceptable).
    
    for i in range(65536):
        # i is 0 to 65535, corresponding to int16 -32768 to 32767
        # struct.unpack('>h', bytes) ...
        # i represents the uint16 view of the int16
        val = i - 65536 if i > 32767 else i
        table[i] = manual_lin2ulaw(val)
        
    global _ULAW_TABLE
    _ULAW_TABLE = table

def _generate_lin_table():
    table = np.zeros(256, dtype=np.int16)
    
    def manual_ulaw2lin(ulaw_byte):
        ulaw_byte = ~ulaw_byte & 0xFF
        sign = ulaw_byte & 0x80
        exponent = (ulaw_byte >> 4) & 0x07
        mantissa = ulaw_byte & 0x0F
        sample = ((mantissa << 3) + 0x84) << exponent
        sample -= 0x84
        if sign != 0:
            sample = -sample
        return sample
        
    for i in range(256):
        table[i] = manual_ulaw2lin(i)
        
    global _LIN_TABLE
    _LIN_TABLE = table

# Initialize tables on import
_generate_ulaw_table()
_generate_lin_table()

def lin2ulaw(frame, width):
    if width != 2:
        raise ValueError("Only width=2 supported")
    
    # data is bytes of int16
    # View as uint16 to use as indices
    indices = np.frombuffer(frame, dtype=np.uint16)
    encoded = _ULAW_TABLE[indices]
    return encoded.tobytes()

def ulaw2lin(frame, width):
    if width != 2:
        raise ValueError("Only width=2 supported")
    
    # frame is bytes of uint8
    indices = np.frombuffer(frame, dtype=np.uint8)
    decoded = _LIN_TABLE[indices]
    return decoded.tobytes()

def resample_24k_to_8k(frame, width):
    if width != 2:
        raise ValueError("Only width=2 supported")
    
    audio = np.frombuffer(frame, dtype=np.int16)
    
    # 24k to 8k is exactly 3:1
    # Check divisibility
    remainder = len(audio) % 3
    if remainder != 0:
        # Pad with last value or zero? 
        # Or just trim. Trimming is safer for stream continuity unless we keep state.
        # But this is simple packet based implementation.
        # Let's trim.
        audio = audio[: -remainder]
    
    # Reshape and mean (simple averaging filter)
    # This reduces aliasing compared to simple decimation (taking every 3rd sample)
    reshaped = audio.reshape(-1, 3)
    downsampled = np.mean(reshaped, axis=1).astype(np.int16)
    
    return downsampled.tobytes(), None # None is state, keeping signature similar to audioop.ratecv which returns (data, state)
