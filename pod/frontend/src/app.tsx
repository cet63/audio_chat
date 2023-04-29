import { useState, ChangeEvent, MouseEvent } from "react";
import { HashRouter, Link, Routes, Route } from "react-router-dom";
import Episode from "./routes/episode";
import Spinner from "./components/Spinner";
import teckStackImgUrl from './whisper-app-tech-stack.png'
import { Search as SearchIcon } from "react-feather";

function NonEnglishLanguageWarning() {
  return (
    <div className="text-yellow-600">
      <span className="mr-2" role="img" aria-label="warning sign">⚠️</span>
      Detected non-English audio. Transcription may be garbage, but amusing.
    </div>
  )
}

// @ts-ignore
function EpisodeCard({ ep }) {
  return (
    <Link to={`/episode/${ep.guid_hash}`} className="px-6 py-1 group">
      <div className="font-bold mb-2 group-hover:underline hover:text-red-500">
        {ep.original_download_link}
      </div>
      {ep.language && !ep.language.startsWith("en") ?
        <NonEnglishLanguageWarning /> : null}
    </Link>

  );
}

// @ts-ignore
function EpList({ eplist }) {
  // @ts-ignore
  const listItems = eplist.map((ep) => (
    <li
      key={ep.guid_hash}
      className="max-w-2xl overflow-hidden border-indigo-400 border-t-2"
    >
      <EpisodeCard ep={ep} />
    </li>
  ));

  return <ul className="py-4 podcast-list">{listItems}</ul>;
}

function Form() {
  const [file, setFile] = useState<File>();
  const [searching, setSearching] = useState(false);
  const [eplist, setEplist] = useState();

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFile(e.target.files[0]);
    }
  };
  const handleFileUpload = async () => {
    if (!file) {
      return;
    }

    console.log(`file#${file.name}, size#${file.size}, type#${file.type}`);
    if (file.size > 100 * 1024 * 1024) {
      console.error(`file#${file.name} is too large!`);
      return;
    }

    setSearching(true);
    const data = new FormData();
    data.append('file', file, file.name)
    const resp = await fetch('/api/upload', {
      method: 'POST',
      body: data,
    });

    if (resp.status !== 200) {
      setSearching(false);
      console.error(`upload file#${file.name} failed, status#${resp.status}`)
      throw new Error("An error occurred: " + resp.status);
    }
    const body = await resp.json();
    setEplist(body);
    setSearching(false);
  };


  return (
    <div className="min-w-full min-h-screen screen pt-8">
      <div className="mx-auto max-w-2xl my-8 shadow-lg rounded-xl bg-white p-6">
        <form className="flex flex-col space-y-5 items-center">
          <div>
            <a
              href="https://modal.com"
              target="_blank"
              rel="noopener noreferrer"
            >
              <img src={teckStackImgUrl} height="300px" alt="" />
            </a>
          </div>
          <div className="text-2xl font-semibold text-gray-700">
            Audio Transcriber and QnA
          </div>

          <div className="mb-2 mt-0 text-xl text-center">
            Transcribe <em>any</em> audio in just 1-2 minutes!
          </div>

          <div className="text-gray-700">
            <p className="mb-4">
              <strong>Upload an audio file<span className="text-red-400">(less than 50MB)</span>. Click on the result to transcribe and chat with it.</strong>
            </p>
            <p className="mb-1">
              <span>If you just want to see some examples, try this: </span>
              <a className="text-indigo-500 no-underline hover:underline" href="/#/episode/3f985a86e2c7948944282ccab50a07a3"><em>Apple Financial Results - Q4 2022</em></a>.
            </p>
          </div>
  
          <div className="w-full flex space-x-2">
            <div className="relative flex-1 w-full">
              <SearchIcon className="absolute top-[11px] left-3 w-5 h-5 text-zinc-500" />
              <input
                type="file"
                accept="audio/*,video/*"
                onChange={onFileChange}
                placeholder="Upload an audio file"
                className="h-10 w-full rounded-md pl-10 text-md text-gray-900 bg-gray-50 border-2 border-zinc-900"
              />
            </div>
            <button
              type="submit"
              onClick={handleFileUpload}
              disabled={searching || !file}
              className="bg-indigo-400 disabled:bg-zinc-500 hover:bg-indigo-600 text-white font-bold py-2 px-4 rounded text-sm w-fit"
            >
              Upload
            </button>
          </div>

          <div>{searching && <Spinner size={10} />}</div>
        </form>
        {eplist && !searching && <EpList eplist={eplist} />}
      </div>
    </div >
  );
}

function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<Form />} />
        <Route path="episode/:episodeId" element={<Episode />} />
      </Routes>
    </HashRouter>
  );
}

export default App;
