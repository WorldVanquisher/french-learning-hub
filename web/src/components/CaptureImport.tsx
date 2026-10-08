import { useRef, useState, type ChangeEvent, type ReactNode } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { OutcomeBanner, type Outcome } from "./ExplicitAction";

// captureIdOf reads capture_id only to look up the stored receipt afterwards. It is
// not validation: the server validates the whole document.
function captureIdOf(value: unknown): string | null {
  if (value && typeof value === "object" && "capture_id" in value) {
    const id = (value as { capture_id: unknown }).capture_id;
    return typeof id === "string" && id.trim() !== "" ? id : null;
  }
  return null;
}

// readFileText uses FileReader, which every target browser (and jsdom) supports.
function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("could not read the file"));
    reader.readAsText(file);
  });
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) return `(${error.status}) ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

// CaptureImport sends one learning_capture_v1 JSON document, unchanged, to
// POST /captures, like the capture CLI. The browser checks only that the text is
// JSON; the server owns every content rule. Import makes no AI call.
export function CaptureImport({
  onImported,
  onOpenRecord,
}: {
  onImported: (entryId: number) => void;
  onOpenRecord: (entryId: number) => void;
}) {
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [checkableId, setCheckableId] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const inFlight = useRef(false);
  // generation ignores a status lookup that finishes after a newer import started.
  const generation = useRef(0);

  // Names differ from the list rows' "Open record #N" so each control is unique.
  function openButton(entryId: number, label = `Open imported record #${entryId}`): ReactNode {
    return (
      <button type="button" className="ghost" onClick={() => onOpenRecord(entryId)}>
        {label}
      </button>
    );
  }

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      setText(await readFileText(file));
      setOutcome(null);
    } catch (error) {
      setOutcome({ kind: "rejected", text: `Could not read ${file.name}: ${describeError(error)}` });
    }
    setCheckableId(null);
  }

  async function submit() {
    if (inFlight.current) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (error) {
      setOutcome({
        kind: "rejected",
        text: `This is not valid JSON, so nothing was sent: ${error instanceof Error ? error.message : String(error)}`,
      });
      setCheckableId(null);
      return;
    }
    const captureId = captureIdOf(parsed);
    const current = ++generation.current;
    inFlight.current = true;
    setPending(true);
    setOutcome(null);
    setCheckableId(null);
    try {
      const result = await api.importCapture(text);
      if (result.created) {
        onImported(result.entry_id);
        setOutcome({
          kind: "succeeded",
          text: (
            <>
              Imported capture <span className="mono">{result.capture_id}</span> as new record #{result.entry_id}
              {result.analysis_id !== null
                ? ` with imported analysis #${result.analysis_id} (unreviewed).`
                : " without an analysis."}{" "}
              {openButton(result.entry_id)}
            </>
          ),
        });
      } else {
        setOutcome({
          kind: "succeeded",
          text: (
            <>
              Already imported: capture <span className="mono">{result.capture_id}</span> with identical
              content is record #{result.entry_id}. Nothing new was stored. {openButton(result.entry_id)}
            </>
          ),
        });
      }
    } catch (error) {
      if (error instanceof NetworkError) {
        setOutcome({
          kind: "uncertain",
          text: `No response was received, so the capture may or may not have been stored.${
            captureId ? " Check its status before importing again." : ""
          } Re-importing the identical document is safe: the server would return the existing record.`,
        });
        setCheckableId(captureId);
      } else if (error instanceof ApiError && error.isConflict && captureId) {
        setOutcome({
          kind: "rejected",
          text: (
            <>
              Conflict ({error.status}): {error.message}. Nothing was changed. A new learning interaction
              needs a new capture_id; correct an interpretation with feedback instead of re-importing.
            </>
          ),
        });
        await showExistingCapture(captureId, current, error);
      } else if (error instanceof ApiError && error.status >= 500) {
        setOutcome({
          kind: "rejected",
          text: `The server reported an error and did not confirm the import (${error.status}): ${error.message}.`,
        });
        setCheckableId(captureId);
      } else {
        setOutcome({
          kind: "rejected",
          text: `The server rejected this capture, so nothing was stored ${describeError(error)}.`,
        });
      }
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }

  // On a conflict the existing receipt is looked up (GET only) so the reader can
  // open the record that already owns this capture_id.
  async function showExistingCapture(captureId: string, current: number, conflict: ApiError) {
    try {
      const receipt = await api.getCaptureReceipt(captureId);
      if (generation.current !== current) return;
      setOutcome({
        kind: "rejected",
        text: (
          <>
            Conflict ({conflict.status}): {conflict.message}. Nothing was changed. The existing capture{" "}
            <span className="mono">{receipt.capture_id}</span> is record #{receipt.entry_id}. A new learning
            interaction needs a new capture_id; correct an interpretation with feedback instead.{" "}
            {openButton(receipt.entry_id, `Open existing record #${receipt.entry_id}`)}
          </>
        ),
      });
    } catch {
      // Keep the conflict message; the lookup is only a convenience.
    }
  }

  async function checkStatus() {
    if (!checkableId) return;
    const current = generation.current;
    setChecking(true);
    try {
      const receipt = await api.getCaptureReceipt(checkableId);
      if (generation.current !== current) return;
      setOutcome({
        kind: "succeeded",
        text: (
          <>
            Stored: capture <span className="mono">{receipt.capture_id}</span> is record #{receipt.entry_id}.{" "}
            {openButton(receipt.entry_id)}
          </>
        ),
      });
      setCheckableId(null);
      onImported(receipt.entry_id);
    } catch (error) {
      if (generation.current !== current) return;
      if (error instanceof ApiError && error.isNotFound) {
        setOutcome({
          kind: "rejected",
          text: `Not stored: no capture ${checkableId} exists on the server. You can import it again.`,
        });
        setCheckableId(null);
      } else {
        setOutcome({
          kind: "uncertain",
          text: `The status check also failed ${describeError(error)}. The import is still unconfirmed.`,
        });
      }
    } finally {
      setChecking(false);
    }
  }

  return (
    <section className="panel" aria-label="Import a learning capture">
      <h2>Import a learning capture</h2>
      <p className="hint">
        Paste or load one <span className="mono">learning_capture_v1</span> JSON document. It is sent
        unchanged to the server, which validates it. Importing makes no AI call. Importing identical
        content again returns the existing record; different content under an existing capture_id is
        refused.
      </p>
      <label className="discovery-search" htmlFor="capture-json">
        Capture JSON
      </label>
      <textarea
        id="capture-json"
        className="capture-json"
        rows={10}
        spellCheck={false}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <div className="actions">
        <label className="file-input">
          Load from file
          <input type="file" accept=".json,application/json" onChange={(event) => void onFile(event)} />
        </label>
        <button
          type="button"
          className="primary"
          disabled={pending || text.trim() === ""}
          onClick={() => void submit()}
        >
          {pending ? "Importing…" : "Import capture"}
        </button>
        {checkableId ? (
          <button type="button" className="ghost" disabled={checking} onClick={() => void checkStatus()}>
            {checking ? "Checking…" : "Check import status"}
          </button>
        ) : null}
      </div>
      <OutcomeBanner outcome={outcome} />
    </section>
  );
}
