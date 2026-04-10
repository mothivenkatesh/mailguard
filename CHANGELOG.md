# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-04-10

### Added
- Initial release
- 9-layer validation pipeline (syntax, typo, disposable, role, free provider, DNS/MX, catch-all, SMTP, scoring)
- Async bulk validation with configurable concurrency
- Typer CLI with single and bulk commands
- Streamlit web UI with drag-drop CSV
- FastAPI REST endpoint
- Docker image
- 800+ disposable domain seed list
- Damerau-Levenshtein typo correction
