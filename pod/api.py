import json
import time
from typing import List, NamedTuple

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import re

from . import config
from .main import (
    get_episode_metadata_path,
    get_transcript_path,
    process_episode,
    search,
    summarize_by_langchain,
    qa_by_langchain,
)
from .podcast import coalesce_short_transcript_segments

logger = config.get_logger(__name__)
web_app = FastAPI()

# A transcription taking > 10 minutes should be exceedingly rare.
MAX_JOB_AGE_SECS = 10 * 60


class InProgressJob(NamedTuple):
    call_id: str
    start_time: int


class SearchItem(BaseModel):
    file_url: str

@web_app.post("/api/search")
async def search_endpoint(item: SearchItem, req: Request):
    logger.info(f"req #{req.url.path} from client#{req.client}, item#{item}")
    file_url = item.file_url.strip()
    if not re.match(r'^(http|https)?:/{2}\w.+$', file_url):
        raise HTTPException(status_code=400, detail="Invalid url")
    return search.call(file_url)


@web_app.get("/api/episode/{guid_hash}")
async def get_episode(guid_hash: str, req: Request):
    logger.info(f"req #{req.url.path} from client#{req.client}, guid_hash#{guid_hash}")
    episode_metadata_path = get_episode_metadata_path(guid_hash)
    transcription_path = get_transcript_path(guid_hash)

    with open(episode_metadata_path, "r") as f:
        metadata = json.load(f)

    if not transcription_path.exists():
        return dict(metadata=metadata)

    with open(transcription_path, "r") as f:
        data = json.load(f)

    return dict(
        metadata=metadata,
        segments=coalesce_short_transcript_segments(data["segments"]),
    )


@web_app.post("/api/transcribe")
async def transcribe_job(episode_id: str, req: Request):
    from modal import container_app

    logger.info(f"req #{req.url.path} from client#{req.client}, episode_id#{episode_id}")
    now = int(time.time())
    try:
        inprogress_job = container_app.in_progress[episode_id]
        # NB: runtime type check is to handle present of old `str` values that didn't expire.
        if (
            isinstance(inprogress_job, InProgressJob)
            and (now - inprogress_job.start_time) < MAX_JOB_AGE_SECS
        ):
            existing_call_id = inprogress_job.call_id
            logger.info(
                f"Found existing, unexpired call ID {existing_call_id} for episode {episode_id}"
            )
            return {"call_id": existing_call_id}
    except KeyError:
        pass

    call = process_episode.spawn(episode_id)
    container_app.in_progress[episode_id] = InProgressJob(
        call_id=call.object_id, start_time=now
    )

    return {"call_id": call.object_id}


@web_app.get("/api/status/{call_id}")
async def poll_status(call_id: str):
    from modal.call_graph import InputInfo, InputStatus
    from modal.functions import FunctionCall

    function_call = FunctionCall.from_id(call_id)
    graph: List[InputInfo] = function_call.get_call_graph()

    try:
        function_call.get(timeout=0.1)
    except TimeoutError:
        pass
    except Exception as exc:
        if exc.args:
            inner_exc = exc.args[0]
            if "HTTPError 403" in inner_exc:
                return dict(error="permission denied on podcast audio download")
        return dict(error="unknown job processing error")

    try:
        map_root = graph[0].children[0].children[0]
    except IndexError:
        return dict(finished=False)

    assert map_root.function_name == "transcribe_episode"

    leaves = map_root.children
    tasks = len(set([leaf.task_id for leaf in leaves]))
    done_segments = len(
        [leaf for leaf in leaves if leaf.status == InputStatus.SUCCESS]
    )
    total_segments = len(leaves)
    finished = map_root.status == InputStatus.SUCCESS

    return dict(
        finished=finished,
        total_segments=total_segments,
        tasks=tasks,
        done_segments=done_segments,
    )


@web_app.get("/api/summarize/{guid_hash}")
async def get_summary(guid_hash: str, req: Request):
    logger.info(f"req #{req.url.path} from client#{req.client}, guid_hash#{guid_hash}")
    result = summarize_by_langchain.call(guid_hash)
    logger.info(f"summarize1#{guid_hash}, result#{result}")
    return result


class QueryItem(BaseModel):
    query: str

@web_app.post("/api/qa/{guid_hash}")
async def get_qa(guid_hash: str, item: QueryItem, req: Request):
    logger.info(f"req #{req.url.path} from client#{req.client}, guid_hash#{guid_hash}, item#{item}")
    query = item.query
    result = qa_by_langchain.call(query, guid_hash)
    logger.info(f"qa#{guid_hash}, query#{query}, result#{result}")
    return result
