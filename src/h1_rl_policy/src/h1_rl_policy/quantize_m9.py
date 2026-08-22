"""M9 quantize hook — dynamic int8 quantization via onnxruntime."""

import os


class QuantizeUnavailableError(Exception):
    """Raised when onnxruntime (or its quantization tooling) is missing."""


def quantize_model(src, dst):
    """Dynamic int8-quantize an ONNX model; returns dst path."""
    try:
        from onnxruntime.quantization import quantize_dynamic
    except ImportError as exc:
        raise QuantizeUnavailableError(
            'onnxruntime not available: {}'.format(exc))
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    quantize_dynamic(src, dst)
    return dst
