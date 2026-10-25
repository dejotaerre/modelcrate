# Contributing

ModelCrate is an experimental Linux GTK4/libadwaita application. The UI is currently Spanish; documentation can be English or Spanish. New code comments should be neutral Spanish.

Use the native Python/GTK dependencies listed in README. Run isolated tests from the repository root:

```sh
python3 -m unittest discover -s tests -v
```

Do not test destructive operations against personal models. Use temporary configurations and a mock HTTP server, as the existing tests do. Avoid committing local paths, credentials, logs, model weights or personal screenshots.

To regenerate the two documented screenshots in a desktop session:

```sh
python3 scripts/screenshots.py --theme dark
python3 scripts/screenshots.py --theme light
```

Before changing hardware heuristics, add cases for missing data, dedicated/shared memory and context changes. Do not label simulation coverage as physical-device validation.

The OpenCode adapter only supports the documented providers format. Unknown schemas should remain untouched. Keep Ollama-only operation available.
