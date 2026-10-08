import { afterEach, describe, expect, it, vi } from "vitest";
import { clearOperation, loadOperations, newOperation, saveOperation } from "./annotationOperation";
import { checkDecision, sendDecision } from "./reviewOutcome";
import { ApiError } from "../api/client";

afterEach(() => { window.localStorage.clear(); vi.restoreAllMocks(); });
describe("durable annotation identity", () => {
  it("stores only the versioned semantic payload and restores the same key", () => {
    const d = newOperation({kind:"relation", unitId:5, conceptId:42, relation:"broader"});
    expect(d.operationId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    saveOperation(d);
    expect(loadOperations()).toEqual([d]);
    saveOperation(loadOperations()[0]);
    expect(loadOperations()).toHaveLength(1);
    expect(() => saveOperation({...d, conceptId:43} as typeof d)).toThrow("payload changed");
    expect(newOperation({kind:"distinct",unitId:5,conceptId:42}).operationId).not.toBe(d.operationId);
    clearOperation(d.operationId!);
    expect(loadOperations()).toEqual([]);
  });
  it("does not pretend failed or corrupt storage is reload-safe", () => {
    window.localStorage.setItem("flh.annotation-operations.v1", "bad json");
    expect(loadOperations).toThrow();
    window.localStorage.clear();
    vi.spyOn(Storage.prototype,"setItem").mockImplementation(() => { throw new Error("quota"); });
    expect(() => saveOperation(newOperation({kind:"distinct",unitId:5,conceptId:42}))).toThrow();
  });
  it("404 is unknown; committed lookup is historical attribution; mismatch is refused", async () => {
    const d = newOperation({kind:"distinct",unitId:5,conceptId:42});
    globalThis.fetch = vi.fn(async () => new Response('{"error":"unknown"}',{status:404}));
    expect(await checkDecision(d,null)).toMatchObject({found:false});
    globalThis.fetch = vi.fn(async () => new Response(JSON.stringify({id:d.operationId,request:{action:"distinct",unit_id:5,concept_id:42},result:{id:17}})));
    expect(await checkDecision(d,null)).toMatchObject({found:true,text:expect.stringContaining("historical")});
    globalThis.fetch = vi.fn(async () => new Response(JSON.stringify({id:d.operationId,request:{action:"distinct",unit_id:6,concept_id:42},result:{id:17}})));
    await expect(checkDecision(d,null)).rejects.toThrow("does not match");
  });
  it("one send never retries automatically", async () => {
    globalThis.fetch = vi.fn(async () => new Response('{"error":"conflict"}',{status:409}));
    await expect(sendDecision(newOperation({kind:"distinct",unitId:5,conceptId:42}))).rejects.toBeInstanceOf(ApiError);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
