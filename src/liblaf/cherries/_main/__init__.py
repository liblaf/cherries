from lazy_loader import attach_stub

__getattr__, __dir__, __all__ = attach_stub(__name__, __file__)

del attach_stub
