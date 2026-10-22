"""One-shot PDF process; JSON output avoids deserializing executable objects."""
import json
import sys


def main():
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
        resource.setrlimit(resource.RLIMIT_FSIZE, (64*1024*1024, 64*1024*1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from invoice_review import _extract_document
    try:
        result = _extract_document(sys.stdin.buffer.read(20*1024*1024+1), 'invoice.pdf')
        print(json.dumps({'result': result}))
    except ValueError as exc:
        print(json.dumps({'error': str(exc)}))
    except Exception:
        print(json.dumps({'error': 'PDF could not be processed. Check the document or upload a smaller PDF.'}))


if __name__ == '__main__':
    main()
