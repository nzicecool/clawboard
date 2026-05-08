# Contributing

We welcome contributions! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/nzicecool/clawboard.git
cd clawboard
pip install -r requirements.txt
python3 app.py
```

The dashboard runs at http://localhost:5000 with auto-reload disabled.

## Project Structure

```
├── app.py                 # Flask routes + data ingestion
├── db.py                  # SQLite database layer
├── guardrail_engine.py    # Health checks + guardrail logic
├── guardrail_config.json  # Guardrail configuration
├── alert_sender.py        # Alert delivery (WhatsApp + email)
├── templates/             # HTML templates (Jinja2)
│   ├── index.html         # Main dashboard
│   ├── token-usage.html   # Token usage page
│   └── health.html        # Health monitor
├── static/                # Static assets
├── docs/                  # GitHub Pages documentation
└── data/                  # SQLite database (gitignored)
```

## Making Changes

1. **Fork** the repo
2. **Create a branch**: `git checkout -b feature/your-feature`
3. **Make changes** and test locally
4. **Commit** with clear messages
5. **Push** and open a Pull Request

## Code Style

- Python: Follow PEP 8
- JavaScript: 2-space indent, semicolons
- HTML: 4-space indent, Tailwind CSS classes

## Adding Features

### New API Endpoint

Add your route in `app.py`:

```python
@app.route('/api/my-endpoint')
def api_my_endpoint():
    data = do_something()
    return jsonify(data)
```

### New Health Check

Add a check function in `guardrail_engine.py` and register it in `run_guardrails()`.

### New Chart

Add a canvas element in the relevant template, then add Chart.js initialization in the `<script>` section.

## Reporting Issues

- Use [GitHub Issues](https://github.com/nzicecool/clawboard/issues)
- Include: OpenClaw version, Python version, OS, error logs
- Steps to reproduce

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
