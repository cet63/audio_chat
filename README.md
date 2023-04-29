# AudioChat

This is a application that uses [OpenAI Whisper](https://github.com/openai/whisper) to transcribe audios, uses [Chroma](https://docs.trychroma.com/) to store vectorized texts, and uses [langchain](https://github.com/hwchase17/langchain) to interact with LLMs.

There is a demo here: https://cet63--pod.modal.run/
, which is forked by [Modal examples](https://github.com/modal-labs/modal-examples/tree/main/06_gpu_and_ml/openai_whisper/pod_transcriber). It splits an audio to small chunks using the ffmpeg `silencedetect` filter, and then Modal spins up 100-300 containers for a single transcription run, so hours of audio can be transcribed on-demand in a few minutes.


## Architecture

The entire application is hosted serverlessly on [Modal](https://modal.com) and consists of 3 components:

1. React + Vite SPA ([`pod/frontend/`](./pod/frontend/))
2. FastAPI server ([`pod/api.py`](./pod/api.py))
3. Modal async job queue ([`pod/main.py`](./pod/main.py))

## Developing locally

### Requirements

- `npm`
- `modal-client` installed in your current Python virtual environment

### OpenAI API-KEY Secret

If you want to use `Summarize` and `Ask`, you'll need to [create a openai account and get an API key](https://platform.openai.com/).

Then, create a [Modal Secret](https://modal.com/secrets/) for OpenAI-API-KEY:

- `my-openai-secret`


### Build the frontend

`cd` into the `pod/frontend` directory, and run:

- `npm install`
- `npx vite build --watch`

The last command will start a watcher process that will rebuild your static frontend files whenever you make changes to the frontend code.

### Serve on Modal

Once you have `vite build` running, in a separate shell run this to start an ephemeral app on Modal:

```shell
modal serve pod.main
```

Pressing `Ctrl+C` will stop your app.

### Deploy to Modal

Once your happy with your changes, run `modal deploy pod.main` to deploy your app to Modal.

## License

The MIT license.
