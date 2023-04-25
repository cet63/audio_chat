"""
whisper-pod-transcriber uses OpenAI's Whisper modal to do speech-to-text transcription
of podcasts.
"""
import datetime
import json
import pathlib
from typing import Iterator, Tuple
import hashlib
import itertools
import re

import requests
import modal

from . import config, podcast

logger = config.get_logger(__name__)
volume = modal.SharedVolume().persist("dataset-cache-vol")

app_image = (
    modal.Image.debian_slim()
    .apt_install("ffmpeg")
    .pip_install(
        "openai-whisper==20230314",
        "dacite",
        "jiwer",
        "ffmpeg-python",
        "pandas",
        "loguru==0.6.0",
        "torchaudio==0.12.1",
        "langchain",
        "chromadb",
        "openai",
        "requests",
    )
)

stub = modal.Stub(
    "pod",
    image=app_image,
    secret=modal.Secret.from_name("my-openai-secret"),
)

stub.in_progress = modal.Dict()


def get_episode_metadata_path(guid_hash: str) -> pathlib.Path:
    return config.EP_METADATA_DIR / f"{guid_hash}.json"

def get_transcript_path(guid_hash: str) -> pathlib.Path:
    return config.TRANSCRIPTIONS_DIR / f"{guid_hash}.json"

def get_vectorindex_path(guid_hash: str) -> pathlib.Path:
    return config.VECTORINDEX_DIR / guid_hash

def get_summary_file(guid_hash: str, method: str) -> pathlib.Path:
    return config.SUMMARY_DIR / f"{guid_hash}_{method}.json"


@stub.function(
    mounts=[
        modal.Mount.from_local_dir(config.ASSETS_PATH, remote_path="/assets")
    ],
    shared_volumes={config.CACHE_DIR: volume},
    keep_warm=2,
)
@modal.asgi_app()
def fastapi_app():
    from fastapi.staticfiles import StaticFiles
    from .api import web_app

    web_app.mount("/", StaticFiles(directory="/assets", html=True))
    return web_app


@stub.function(
    image=app_image,
    shared_volumes={config.CACHE_DIR: volume},
)
def search(file_url: str):
    logger.info(f"Searching for '{file_url}'")
    pattern = r'https?://[^\s]+\.mp[34]'
    if re.match(pattern, file_url):
        return [process_url(file_url)]
    
    headers = {
        "user-agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36"
    }
    ret = requests.get(file_url, headers=headers)
    text = ret.text
    links = re.findall(pattern, text)
    links = set([x.strip() for x in links])
    return list(map(process_url, links))
    
def process_url(file_url: str):
    url_hash = hashlib.md5(file_url.encode('utf-8')).hexdigest()

    ep_metadata_path = get_episode_metadata_path(url_hash)
    logger.info(f"process_url#'{file_url}', hash#{url_hash}")
    if not ep_metadata_path.exists():
        ep_metadata_path.parent.mkdir(parents=True, exist_ok=True)

        ep_metadata = {
            "guid_hash": url_hash,
            "transcribed": False,
            "original_download_link": file_url,
            "publish_date": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(ep_metadata_path, "w") as f:
            json.dump(ep_metadata, f)

        logger.info(f"Searching for '{file_url}', wrote metadata to #{ep_metadata_path}, success#{ep_metadata_path.exists()}")
        return ep_metadata

    with open(ep_metadata_path, "r") as f:
        return json.load(f)


def split_silences(
    path: str, min_segment_length: float = 30.0, min_silence_length: float = 1.0
) -> Iterator[Tuple[float, float]]:
    """Split audio file into contiguous chunks using the ffmpeg `silencedetect` filter.
    Yields tuples (start, end) of each chunk in seconds."""

    import re
    import ffmpeg

    silence_end_re = re.compile(
        r" silence_end: (?P<end>[0-9]+(\.?[0-9]*)) \| silence_duration: (?P<dur>[0-9]+(\.?[0-9]*))"
    )

    metadata = ffmpeg.probe(path)
    duration = float(metadata["format"]["duration"])

    reader = (
        ffmpeg.input(str(path))
        .filter("silencedetect", n="-10dB", d=min_silence_length)
        .output("pipe:", format="null")
        .run_async(pipe_stderr=True)
    )

    cur_start = 0.0
    num_segments = 0

    while True:
        line = reader.stderr.readline().decode("utf-8")
        if not line:
            break
        match = silence_end_re.search(line)
        if match:
            silence_end, silence_dur = match.group("end"), match.group("dur")
            split_at = float(silence_end) - (float(silence_dur) / 2)

            if (split_at - cur_start) < min_segment_length:
                continue

            yield cur_start, split_at
            cur_start = split_at
            num_segments += 1

    # silencedetect can place the silence end *after* the end of the full audio segment.
    # Such segments definitions are negative length and invalid.
    if duration > cur_start and (duration - cur_start) > min_segment_length:
        yield cur_start, duration
        num_segments += 1
    logger.info(f"Split {path} into {num_segments} segments")


@stub.function(
    image=app_image,
    shared_volumes={config.CACHE_DIR: volume},
    cpu=2,
)
def transcribe_segment(
    start: float,
    end: float,
    audio_filepath: pathlib.Path,
    model: config.ModelSpec,
):
    import tempfile
    import time

    import ffmpeg
    import torch
    import whisper

    t0 = time.time()
    with tempfile.NamedTemporaryFile(suffix=".mp3") as f:
        (
            ffmpeg.input(str(audio_filepath))
            .filter("atrim", start=start, end=end)
            .output(f.name)
            .overwrite_output()
            .run(quiet=True)
        )

        use_gpu = torch.cuda.is_available()
        device = "cuda" if use_gpu else "cpu"
        m = whisper.load_model(
            model.name, device=device, download_root=str(config.MODEL_DIR)
        )
        #result = m.transcribe(f.name, language="en", fp16=use_gpu)  # type: ignore
        result = m.transcribe(f.name, fp16=use_gpu)

    logger.info(
        f"Transcribed segment {start:.2f} to {end:.2f} ({end - start:.2f}s duration) in {time.time() - t0:.2f} seconds."
    )

    # Add back offsets.
    for segment in result["segments"]:
        segment["start"] += start
        segment["end"] += start

    return result


@stub.function(
    image=app_image,
    shared_volumes={config.CACHE_DIR: volume},
    timeout=900,
)
def transcribe_episode(
    audio_filepath: pathlib.Path,
    result_path: pathlib.Path,
    model: config.ModelSpec,
):
    segment_gen = split_silences(str(audio_filepath))

    output_text = ""
    output_segments = []
    language = "en"
    for result in transcribe_segment.starmap(
        segment_gen, kwargs=dict(audio_filepath=audio_filepath, model=model)
    ):
        output_text += result["text"]
        output_segments += result["segments"]
        language = result["language"]

    result = {
        "text": output_text,
        "segments": output_segments,
        "language": language, # auto-detect
    }

    logger.info(f"Writing openai/whisper transcription to {result_path}")
    with open(result_path, "w") as f:
        json.dump(result, f, indent=4)
    
    # free the storage space
    if audio_filepath.exists():
        audio_filepath.unlink()
        logger.info(f"Delete raw-audio file#{audio_filepath} successfully")


@stub.function(
    image=app_image,
    shared_volumes={config.CACHE_DIR: volume},
    timeout=900,
)
def process_episode(episode_id: str):
    import dacite
    import whisper

    from modal import container_app

    try:
        # pre-download the model to the cache path, because the _download fn is not
        # thread-safe.
        model = config.DEFAULT_MODEL
        whisper._download(whisper._MODELS[model.name], str(config.MODEL_DIR), False)

        config.RAW_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        config.TRANSCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)

        metadata_path = get_episode_metadata_path(episode_id)
        with open(metadata_path, "r") as f:
            data = json.load(f)
            episode = dacite.from_dict(
                data_class=podcast.EpisodeMetadata, data=data
            )

        destination_path = config.RAW_AUDIO_DIR / episode_id
        podcast.store_original_audio(
            url=episode.original_download_link,
            destination=destination_path,
        )

        logger.info(
            f"Using the {model.name} model which has {model.params} parameters."
        )
        logger.info(f"Wrote episode metadata to {metadata_path}")

        transcription_path = get_transcript_path(episode.guid_hash)
        if transcription_path.exists():
            logger.info(
                f"Transcription already exists for episode#{episode.guid_hash}."
            )
            logger.info("Skipping transcription.")
        else:
            transcribe_episode.call(
                audio_filepath=destination_path,
                result_path=transcription_path,
                model=model,
            )

            with open(metadata_path, "w") as f:
                data["transcribed"] = True
                json.dump(data, f)

    finally:
        del container_app.in_progress[episode_id]

    return episode


def get_segments(guid_hash: str):
    transcription_path = get_transcript_path(guid_hash)
    with open(transcription_path, "r") as f:
        data = json.load(f)
    return podcast.coalesce_short_transcript_segments(data["segments"])

def merge(orig_list: list[str]) -> list[str]:
    new_list = []
    s1 = ''
    length = len(orig_list)
    for i in range(0, length):
        s1 += ('' if s1 == '' else ' ') + orig_list[i]
        if len(s1)>=1000 or  i is length-1:
            new_list.append(s1)
            s1 = ''
    return new_list

def get_vector_index(guid_hash: str):
    from langchain.vectorstores import Chroma
    from langchain.embeddings.openai import OpenAIEmbeddings
    #embeddings = create_retrying_openai_embeddings()
    embeddings = OpenAIEmbeddings()
    index_path = get_vectorindex_path(guid_hash)
    if not index_path.exists():
        segments = get_segments(guid_hash)
        texts = merge([t["text"] for t in segments])
        logger.debug(f"get_vector_index, t0#{texts[0]}")
        logger.debug(f"get_vector_index, t3#{texts[3]}")

        index_path.mkdir(parents=True, exist_ok=True)
        # supplying a persist_directory will store the embeddings on disk
        vectordb = Chroma.from_texts(texts=texts, embedding=embeddings, persist_directory=str(index_path))

        # persist the Database
        vectordb.persist()
    else:
        # load the persisted database from disk
        vectordb = Chroma(embedding_function=embeddings, persist_directory=str(index_path))

    return vectordb

@stub.function(
    image=app_image,
    secret=modal.Secret.from_name("my-openai-secret"),
    shared_volumes={config.CACHE_DIR: volume},
    timeout=1000,
)
def qa_by_langchain(query: str, guid_hash: str) -> str:
    from langchain.llms import OpenAI
    from langchain.chains.question_answering import load_qa_chain
    '''
    # Works well, but too expensive😓
    from langchain.chains import AnalyzeDocumentChain
    qa_chain = load_qa_chain(OpenAI(temperature=0), chain_type="map_reduce")
    qa_document_chain = AnalyzeDocumentChain(combine_docs_chain=qa_chain)

    segments = get_segments(guid_hash)
    text = ' '.join([t["text"] for t in segments])
    output_text = qa_document_chain.run(input_document=text, question=query)
    logger.info(f"output_text#{output_text}")
    return output_text'''
    
    from langchain.chains import RetrievalQA
    vectordb = get_vector_index(guid_hash)
    qa_chain = load_qa_chain(OpenAI(temperature=0), chain_type="stuff")
    qa = RetrievalQA(combine_documents_chain=qa_chain, retriever=vectordb.as_retriever())
    return qa.run(query)


@stub.function(
    image=app_image,
    secret=modal.Secret.from_name("my-openai-secret"),
    shared_volumes={config.CACHE_DIR: volume},
    timeout=900,
)
def summarize_by_langchain(guid_hash: str, method: str = "1") -> str:
    summary_file = get_summary_file(guid_hash, method)
    if summary_file.exists():
        with open(summary_file, "r") as f:
            return f.read()

    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize_by_langchain_1(guid_hash)

    with open(summary_file, "w") as f:
        f.write(summary)
    logger.info(f"summary({method}) guid_hash#{guid_hash}, and wrote to file#{summary_file}, result#{summary}")
    return summary

# by AnalyzeDocumentChain
def summarize_by_langchain_1(guid_hash: str) -> str:
    from langchain import OpenAI
    from langchain.chains.summarize import load_summarize_chain
    from langchain.chains import AnalyzeDocumentChain

    summary_chain = load_summarize_chain(OpenAI(temperature=0.01), chain_type="map_reduce")
    summarize_document_chain = AnalyzeDocumentChain(combine_docs_chain=summary_chain)

    segments = get_segments(guid_hash)
    text = ' '.join([t["text"] for t in segments])
    return summarize_document_chain.run(text)

# by summarize_chain
def summarize_by_langchain_2(guid_hash: str) -> str:
    from langchain import OpenAI
    from langchain.chains.summarize import load_summarize_chain
    from langchain.docstore.document import Document

    summary_chain = load_summarize_chain(OpenAI(temperature=0), chain_type="map_reduce")

    segments = get_segments(guid_hash)
    docs = [Document(page_content=t["text"]) for t in segments]
    return summary_chain.run(docs)


def create_retrying_openai_embeddings():
    """
    New OpenAI accounts have a very low rate-limit for their first 48 hrs.
    It's too low to embed even just this single Biden speech.
    As a workaround this wrapper handles rate-limit errors and slows embedding requests.
    Ref: https://platform.openai.com/docs/guides/rate-limits/overview.
    """
    from tenacity import retry, wait_exponential
    from langchain.embeddings.openai import OpenAIEmbeddings

    def batched(iterable, n):
        if n < 1:
            raise ValueError("n must be at least one")
        it = iter(iterable)
        batch = list(itertools.islice(it, n))
        while batch:
            yield batch
            batch = list(itertools.islice(it, n))

    class RetryingEmbedder(OpenAIEmbeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            retrying_fn = retry(
                wait=wait_exponential(multiplier=1, min=4, max=10)
            )(super().embed_documents)
            all_embeddings = []
            for i, batch in enumerate(batched(texts, n=5)):
                print(f"embedding documents batch {i}...")
                all_embeddings.extend(retrying_fn(batch))
            return all_embeddings

    return RetryingEmbedder()
