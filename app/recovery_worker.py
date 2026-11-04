"""Limit a fallback collector before importing parsers into a small web instance."""
import runpy

MEMORY_BYTES = 320 * 1024 * 1024


def limit_memory():
    try:
        import resource
    except ImportError:
        return  # Windows local tests; production Render uses Linux.
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    ceiling = MEMORY_BYTES if hard == resource.RLIM_INFINITY else min(MEMORY_BYTES, hard)
    if soft != resource.RLIM_INFINITY:
        ceiling = min(ceiling, soft)
    resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))


if __name__ == '__main__':
    limit_memory()
    runpy.run_module('app.snapshot_export', run_name='__main__', alter_sys=True)
