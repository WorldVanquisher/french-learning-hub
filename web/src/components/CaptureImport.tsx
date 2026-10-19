import { useRef, useState, type ChangeEvent, type ReactNode } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { OutcomeBanner, type Outcome } from "./ExplicitAction";
import { msg, useI18n, type I18n } from "../i18n";

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
  const { t, tn } = useI18n();
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [checkableId, setCheckableId] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const inFlight = useRef(false);
  // generation ignores a status lookup that finishes after a newer import started.
  const generation = useRef(0);

  // Names differ from the list rows' "Open record #N" so each control is unique.
  function openButton(i: I18n, entryId: number, existing = false): ReactNode {
    return (
      <button type="button" className="ghost" onClick={() => onOpenRecord(entryId)}>
        {i.t(existing ? "capture.openExisting" : "capture.openImported", { id: entryId })}
      </button>
    );
  }
  const mono = (value: string) => <span className="mono">{value}</span>;

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      setText(await readFileText(file));
      setOutcome(null);
    } catch (error) {
      setOutcome({ kind: "rejected", text: msg("capture.readFailed", { file: file.name, error: describeError(error) }) });
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
        text: msg("capture.notJson", { error: error instanceof Error ? error.message : String(error) }),
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
          text: (i) =>
            i.tn(result.analysis_id !== null ? "capture.imported.withAnalysis" : "capture.imported.withoutAnalysis", {
              capture: mono(result.capture_id),
              record: result.entry_id,
              analysis: result.analysis_id ?? "",
              open: openButton(i, result.entry_id),
            }),
        });
      } else {
        setOutcome({
          kind: "succeeded",
          text: (i) =>
            i.tn("capture.alreadyImported", {
              capture: mono(result.capture_id),
              record: result.entry_id,
              open: openButton(i, result.entry_id),
            }),
        });
      }
    } catch (error) {
      if (error instanceof NetworkError) {
        setOutcome({
          kind: "uncertain",
          text: msg(captureId ? "capture.noResponse.checkable" : "capture.noResponse"),
        });
        setCheckableId(captureId);
      } else if (error instanceof ApiError && error.isConflict && captureId) {
        setOutcome({
          kind: "rejected",
          text: msg("capture.conflict", { status: error.status, message: error.message }),
        });
        await showExistingCapture(captureId, current, error);
      } else if (error instanceof ApiError && error.status >= 500) {
        setOutcome({
          kind: "rejected",
          text: msg("capture.serverError", { status: error.status, message: error.message }),
        });
        setCheckableId(captureId);
      } else {
        setOutcome({
          kind: "rejected",
          text: msg("capture.rejected", { error: describeError(error) }),
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
        text: (i) =>
          i.tn("capture.conflictExisting", {
            status: conflict.status,
            message: conflict.message,
            capture: mono(receipt.capture_id),
            record: receipt.entry_id,
            open: openButton(i, receipt.entry_id, true),
          }),
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
        text: (i) =>
          i.tn("capture.stored", { capture: mono(receipt.capture_id), record: receipt.entry_id, open: openButton(i, receipt.entry_id) }),
      });
      setCheckableId(null);
      onImported(receipt.entry_id);
    } catch (error) {
      if (generation.current !== current) return;
      if (error instanceof ApiError && error.isNotFound) {
        setOutcome({
          kind: "rejected",
          text: msg("capture.notStored", { capture: checkableId }),
        });
        setCheckableId(null);
      } else {
        setOutcome({
          kind: "uncertain",
          text: msg("capture.checkFailed", { error: describeError(error) }),
        });
      }
    } finally {
      setChecking(false);
    }
  }

  return (
    <section className="panel" aria-label={t("capture.title")}>
      <h2>{t("capture.title")}</h2>
      <p className="hint">{tn("capture.hint", { schema: <span className="mono">learning_capture_v1</span> })}</p>
      <label className="discovery-search" htmlFor="capture-json">
        {t("capture.jsonLabel")}
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
          {t("capture.loadFile")}
          <input type="file" accept=".json,application/json" onChange={(event) => void onFile(event)} />
        </label>
        <button
          type="button"
          className="primary"
          disabled={pending || text.trim() === ""}
          onClick={() => void submit()}
        >
          {pending ? t("capture.importing") : t("capture.import")}
        </button>
        {checkableId ? (
          <button type="button" className="ghost" disabled={checking} onClick={() => void checkStatus()}>
            {checking ? t("capture.checking") : t("capture.checkStatus")}
          </button>
        ) : null}
      </div>
      <OutcomeBanner outcome={outcome} />
    </section>
  );
}
