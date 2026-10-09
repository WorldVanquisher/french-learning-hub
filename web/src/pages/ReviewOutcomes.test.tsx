import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ReviewQueue } from "./ReviewQueue";
import { checkDecision } from "./reviewOutcome";

// Concept Review decision outcomes, rendered in StrictMode as main.tsx does. A
// stateful fixture backend lets a write either never arrive ("not sent"), or be
// committed and then lose its response ("lost response"), the case browser
// acceptance reproduced.
afterEach(() => { cleanup(); window.localStorage.clear(); vi.restoreAllMocks(); });

type Reply = { status?: number; body: unknown } | "network-error";
type Handler = (body: unknown) => Reply | Promise<Reply>;

function deferred() {
  let resolve!: (reply: Reply) => void;
  const promise = new Promise<Reply>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const reviewable = (id: number) => ({
  unit_id: id,
  kind: "grammar",
  canonical: `unit ${id}`,
  statement: `Énoncé ${id}`,
  example: null,
  confidence: 0.9,
  candidate_identity: { target: `cible ${id}`, pedagogical_intent: "grammar", scope: "", identity_features: {} },
  signature: "{...}",
});

const concept = (id: number, target: string) => ({
  id,
  identity_schema_version: "fr_l2_concept_identity_v1",
  target,
  pedagogical_intent: "grammar",
  scope: "",
  identity_features: {},
  signature: "{...}",
  preferred_unit_id: null,
  state: "orphaned",
  lifecycle_state: "normal",
  support_state: "orphaned",
  created_at: "t",
  updated_at: "t",
});

type Mode =
  | "ok"
  | "not-sent"
  | "lost"
  | { reject: number; error: string }
  | { slow: ReturnType<typeof deferred> }
  // The request never arrives, but something else changes the backend meanwhile.
  | { notSentButElsewhere: () => void };

// A minimal backend for units 5 and 6 and concept #42 (an exact match for unit 5).
function backend() {
  const memberships = new Map<number, { concept_id: number; link_id: number; updated_at: string }>();
  const invalid = new Set<number>();
  const distinctions: Array<{ id: number; unit_id: number; concept_id: number }> = [{ id: 3, unit_id: 5, concept_id: 42 }];
  const links: Array<{ id: number; unit_id: number; concept_id: number; relation: string; status: string }> = [];
  const concepts = [concept(42, "cible 5")];
  let nextId = 100;
  const writeMode = new Map<string, Mode>();
  const calls: Array<{ method: string; path: string }> = [];
  const receipts = new Map<string, unknown>();
  const reads = new Map<string, Mode>();

  // commit applies a write to the fixture state, as the real backend would.
  const commit = (key: string, body: Record<string, unknown>): unknown => {
    const unitId = Number(key.match(/knowledge-units\/(\d+)/)?.[1] ?? body.seed_unit_id);
    if (key.endsWith("/concept-links/same")) {
      const link = nextId++;
      memberships.set(unitId, { concept_id: body.concept_id as number, link_id: link, updated_at: "t" });
      return { id: link, unit_id: unitId, concept_id: body.concept_id, relation: "same", status: "accepted" };
    }
    if (key === "POST /api/concepts") {
      const identity = body.identity as { target: string };
      const created = { ...concept(nextId++, identity.target) };
      concepts.push(created);
      const link = nextId++;
      memberships.set(unitId, { concept_id: created.id, link_id: link, updated_at: "t" });
      return { concept: created, link: { id: link } };
    }
    if (key.endsWith("/concept-distinctions")) {
      const d = { id: nextId++, unit_id: unitId, concept_id: body.concept_id as number };
      distinctions.push(d);
      return d;
    }
    if (key.endsWith("/concept-links/relation")) {
      const l = { id: nextId++, unit_id: unitId, concept_id: body.concept_id as number, relation: body.relation as string, status: "accepted" };
      links.push(l);
      return l;
    }
    if (key.endsWith("/invalid")) {
      invalid.add(unitId);
      memberships.delete(unitId);
      return { unit_id: unitId, invalid: true, current_membership: null, judgment: { id: nextId++ } };
    }
    throw new Error(`no commit for ${key}`);
  };

  const write = (key: string): Handler => async (body) => {
    const mode = writeMode.get(key) ?? "ok";
    if (mode === "not-sent") return "network-error";
    if (typeof mode === "object" && "notSentButElsewhere" in mode) {
      mode.notSentButElsewhere();
      return "network-error";
    }
    if (typeof mode === "object" && "reject" in mode) return { status: mode.reject, body: { error: mode.error } };
    if (typeof mode === "object" && "slow" in mode) {
      const reply = await mode.slow.promise;
      if (reply !== "network-error") commit(key, body as Record<string, unknown>);
      return reply;
    }
    const result = commit(key, body as Record<string, unknown>);
    return mode === "lost" ? "network-error" : { status: 201, body: result };
  };

  const read = (key: string, answer: () => unknown): Handler => async () => {
    const mode = reads.get(key);
    if (mode && typeof mode === "object" && "reject" in mode) {
      reads.delete(key);
      return { status: mode.reject, body: { error: mode.error } };
    }
    if (mode && typeof mode === "object" && "slow" in mode) {
      reads.delete(key);
      await mode.slow.promise;
    }
    return { body: answer() };
  };

  const handlers: Record<string, Handler> = {
    "GET /api/reviewable-units": read("reviewable", () => ({
      reviewable_units: [5, 6].filter((id) => !memberships.has(id) && !invalid.has(id)).map(reviewable),
    })),
    "GET /api/concepts": read("concepts", () => ({ concepts })),
    "GET /api/concepts/42": read("concept42", () => ({ concept: concepts[0], links: links.filter((l) => l.concept_id === 42) })),
    "POST /api/concepts": write("POST /api/concepts"),
  };
  for (const id of [5, 6]) {
    handlers[`GET /api/knowledge-units/${id}/concept-membership`] = read(`membership${id}`, () => ({ unit_id: id, current_membership: memberships.get(id) ?? null }));
    handlers[`GET /api/knowledge-units/${id}/concept-resolution`] = read(`resolution${id}`, () => ({
      unit_id: id,
      decision: id === 5 ? "matched" : "no_match",
      matches: id === 5 ? [concepts[0]] : [],
    }));
    handlers[`GET /api/knowledge-units/${id}/concept-distinctions`] = read(`distinctions${id}`, () => ({ unit_id: id, distinctions: distinctions.filter((d) => d.unit_id === id) }));
    handlers[`GET /api/knowledge-units/${id}/effective-annotation`] = async () => ({body:{unit_id:id, effective_annotation:{}}});
    handlers[`GET /api/knowledge-units/${id}/invalid`] = read(`invalid${id}`, () => ({ unit_id: id, invalid: invalid.has(id), history: invalid.has(id) ? [{ id: 99, judgment: "invalid" }] : [] }));
    for (const suffix of ["concept-links/same", "concept-distinctions", "concept-links/relation", "invalid"]) {
      handlers[`POST /api/knowledge-units/${id}/${suffix}`] = write(`POST /api/knowledge-units/${id}/${suffix}`);
    }
  }
  // The NEW CONCEPT check reads the created concept by ID.
  const conceptById = (id: number) => concepts.find((c) => c.id === id);

  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = new URL(String(input), "http://localhost").pathname;
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path });
    let handler = handlers[`${method} ${path}`];
    const byId = path.match(/^\/api\/concepts\/(\d+)$/);
    if (!handler && method === "GET" && byId && conceptById(Number(byId[1]))) {
      handler = async () => ({ body: { concept: conceptById(Number(byId[1])), links: [] } });
    }
    const operationId = new Headers(init?.headers).get("Idempotency-Key");
    const lookup = path.match(/^\/api\/annotation-operations\/(.+)$/);
    if (lookup) handler = read("receipt", () => receipts.get(lookup[1]));
    if (lookup && !receipts.has(lookup[1])) handler = async () => ({status:404, body:{error:"unknown"}});
    if (operationId && receipts.has(operationId)) handler = async () => ({status:201, body:(receipts.get(operationId) as {result:unknown}).result});
    const beforeEvents = nextId;
    const reply = handler ? await handler(body) : { status: 404, body: { error: "not found" } };
    if (operationId && nextId > beforeEvents) {
      const event = [...distinctions, ...links].find((e) => e.id === beforeEvents)!;
      receipts.set(operationId, {schema_version:"annotation_operation_v1", id:operationId, state:"committed", status:201,
        request:{action:path.endsWith("concept-distinctions") ? "distinct" : "relation", unit_id:event.unit_id, concept_id:event.concept_id, ...(body.relation ? {relation:body.relation} : {})}, result:event});
    }
    if (reply === "network-error") throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;

  return {
    writeMode,
    reads,
    memberships,
    distinctions,
    links,
    invalid,
    posts: (suffix: string) => calls.filter((c) => c.method === "POST" && c.path.endsWith(suffix)).length,
  };
}

async function renderQueue() {
  const result = render(
    <StrictMode>
      <ReviewQueue />
    </StrictMode>,
  );
  await screen.findByText("Énoncé 5");
  await waitFor(() => expect(screen.getByRole("button", { name: "SAME → selected" })).toBeEnabled());
  return result;
}

const decision = (name: string) => screen.getByRole("button", { name });
const panel = () => screen.queryByRole("region", { name: "Unknown decision outcome" });

async function banner(role: "status" | "alert", text: string | RegExp): Promise<HTMLElement> {
  const matches = (el: HTMLElement) =>
    typeof text === "string" ? (el.textContent ?? "").includes(text) : text.test(el.textContent ?? "");
  let found: HTMLElement | undefined;
  await waitFor(() => {
    found = screen.queryAllByRole(role).find(matches);
    expect(found, `no ${role} containing ${String(text)}`).toBeDefined();
  });
  return found as HTMLElement;
}

describe("Missing response: never reported as failure", () => {
  it("request never arrived: unknown outcome, check finds nothing, stays blocked, no resend", async () => {
    const b = backend();
    b.writeMode.set("POST /api/concepts", "not-sent");
    await renderQueue();
    fireEvent.change(screen.getByLabelText("target"), { target: { value: "cible éditée" } });
    fireEvent.click(decision("NEW CONCEPT"));

    const unknown = await banner("alert", "Outcome unknown.");
    expect(unknown).toHaveTextContent('No response was received for NEW CONCEPT "cible éditée" with SAME on unit #5, so it may or may not have been recorded. It was not sent again.');
    expect(unknown).not.toHaveTextContent(/could not be recorded|failed/i);
    await waitFor(() => expect(panel()).toHaveTextContent("Not visible on the server yet: The unit has no current SAME membership."));
    expect(panel()).toHaveTextContent("The original request may still be in progress on the server, or may never have arrived.");
    for (const name of ["SAME → selected", "NEW CONCEPT", "DISTINCT", "INVALID"]) expect(decision(name)).toBeDisabled();
    // The identity draft is kept for an informed retry.
    expect(screen.getByLabelText("target")).toHaveValue("cible éditée");
    expect(b.posts("/api/concepts")).toBe(1);
  });

  it("committed NEW CONCEPT with a lost response: the check finds it and the unit leaves the queue", async () => {
    const b = backend();
    b.writeMode.set("POST /api/concepts", "lost");
    await renderQueue();
    fireEvent.click(decision("NEW CONCEPT"));

    const notice = await banner("status", /Unit #5: the server shows NEW CONCEPT "cible 5" with SAME is stored \(The unit now belongs to concept #\d+ \("cible 5"\), matching the drafted identity\.\), so the unit left the queue\./);
    expect(notice).toBeInTheDocument();
    await screen.findByText("Énoncé 6");
    expect(screen.queryByText("Énoncé 5")).not.toBeInTheDocument();
    expect(b.posts("/api/concepts")).toBe(1);
    expect(b.memberships.has(5)).toBe(true);
  });

  it.each([
    { name: "SAME → selected", suffix: "/concept-links/same", found: "The unit's current SAME membership is concept #42" },
    { name: "INVALID", suffix: "/invalid", found: "The unit is INVALID" },
  ])("committed $name with a lost response is found and the unit leaves the queue", async ({ name, suffix, found }) => {
    const b = backend();
    b.writeMode.set(`POST /api/knowledge-units/5${suffix}`, "lost");
    await renderQueue();
    fireEvent.click(decision(name));
    await banner("status", found);
    await screen.findByText("Énoncé 6");
    expect(b.posts(`/api/knowledge-units/5${suffix}`)).toBe(1);
  });

  it("committed DISTINCT with a lost response: receipt attributes this request", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", "lost");
    await renderQueue();
    fireEvent.click(decision("DISTINCT"));
    // The older event is not this request; the keyed receipt attributes the new event.
    await banner("status", /Found on the server: This request committed event #\d+/);
    // A DISTINCT does not change membership; the unit stays and decisions are possible again.
    expect(screen.getByText("Énoncé 5")).toBeInTheDocument();
    await waitFor(() => expect(decision("NEW CONCEPT")).toBeEnabled());
    await banner("status", "Unit #5's membership and exact matches re-read from the server.");
    expect(b.distinctions.filter((d) => d.unit_id === 5)).toHaveLength(2);
  });

  it("DISTINCT that never arrived is not mistaken for the older stored event", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", "not-sent");
    await renderQueue();
    fireEvent.click(decision("DISTINCT"));
    await waitFor(() => expect(panel()).toHaveTextContent("Receipt unknown."));
    expect(decision("NEW CONCEPT")).toBeDisabled();
  });

  it("committed relation with a lost response is attributed by receipt", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-links/relation", "lost");
    await renderQueue();
    fireEvent.click(decision("BROADER"));
    await banner("status", /Found on the server: This request committed event #\d+/);
    expect(b.links).toHaveLength(1);
    expect(b.posts("/concept-links/relation")).toBe(1);
  });
});

describe("Informed recovery", () => {
  it("a failed check is reported; Check again finds the stored decision", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", "lost");
    await renderQueue();
    // Fail the receipt lookup following the lost POST.
    const original = globalThis.fetch;
    let failNextDistinctionRead = false;
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if ((init?.method ?? "GET") === "POST" && path.endsWith("/concept-distinctions")) failNextDistinctionRead = true;
      else if (failNextDistinctionRead && path.includes("/annotation-operations/")) {
        failNextDistinctionRead = false;
        return new Response(JSON.stringify({ error: "could not fetch distinctions" }), { status: 500, headers: { "Content-Type": "application/json" } });
      }
      return original(input, init);
    }) as typeof fetch;

    fireEvent.click(decision("DISTINCT"));
    const failed = await screen.findByText(/could not fetch distinctions/);
    expect(failed).toBeInTheDocument();
    expect(decision("NEW CONCEPT")).toBeDisabled();

    fireEvent.click(within(panel() as HTMLElement).getByRole("button", { name: "Check receipt" }));
    await banner("status", /Found on the server: This request committed event #\d+/);
    expect(b.posts("/concept-distinctions")).toBe(1);
  });

  it("explicit retry keeps the saved operation, and a new decision uses a fresh key", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", "not-sent");
    const first = await renderQueue();
    fireEvent.click(decision("DISTINCT"));
    await waitFor(() => expect(panel()).toHaveTextContent("Receipt unknown"));
    const saved = window.localStorage.getItem("flh.annotation-operations.v1");
    first.unmount();
    render(<StrictMode><ReviewQueue /></StrictMode>);
    await screen.findByText("Énoncé 5");
    expect(panel()).toHaveTextContent("Restored unresolved operation");
    expect(decision("NEW CONCEPT")).toBeDisabled();
    expect(b.posts("/concept-distinctions")).toBe(1);
    b.writeMode.delete("POST /api/knowledge-units/5/concept-distinctions");
    await waitFor(() => expect(screen.getByRole("button", {name:"selected"})).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", {name:"selected"}));
    fireEvent.click(screen.getByRole("button", {name:"Retry saved operation"}));
    await banner("status", "Recorded DISTINCT");
    expect(b.posts("/concept-distinctions")).toBe(2);
    expect(b.distinctions).toHaveLength(2);
    const posts = vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST");
    const keys = posts.map(([,init]) => new Headers(init?.headers).get("Idempotency-Key"));
    expect(keys[0]).toBe(keys[1]);
    expect(posts[0][1]?.body).toBe(posts[1][1]?.body);
    expect(saved).toContain(keys[0]!);
    await waitFor(() => expect(decision("NEW CONCEPT")).toBeEnabled());
    fireEvent.click(screen.getByRole("button", {name:"select this concept"}));
    fireEvent.click(decision("DISTINCT"));
    await waitFor(() => expect(b.posts("/concept-distinctions")).toBe(3));
    const last = vi.mocked(fetch).mock.calls.filter(([,init]) => init?.method === "POST").at(-1)!;
    expect(new Headers(last[1]?.headers).get("Idempotency-Key")).not.toBe(keys[0]);
  });

  it("storage failure prevents a new keyed POST and says reload recovery is unavailable", async () => {
    const b = backend();
    await renderQueue();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {throw new Error("quota");});
    fireEvent.click(decision("DISTINCT"));
    await screen.findByText(/Browser storage failed. Nothing was sent/);
    expect(b.posts("/concept-distinctions")).toBe(0);
  });

  it("committed receipt remains attributed even when current-authority refresh fails", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", "lost");
    await renderQueue();
    b.reads.set("membership5", {reject:500,error:"refresh unavailable"});
    fireEvent.click(decision("DISTINCT"));
    await banner("status", /This request committed event/);
    await banner("alert", /refresh unavailable/);
    expect(screen.queryByText("Outcome unknown.")).not.toBeInTheDocument();
    expect(b.posts("/concept-distinctions")).toBe(1);
  });

  it("an explicit server rejection is definite: no reconciliation and no block", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-links/same", { reject: 422, error: "validation error\nconcept is retired" });
    await renderQueue();
    fireEvent.click(decision("SAME → selected"));
    await banner("alert", "The server did not record SAME → concept #42 (422) validation error\nconcept is retired.");
    expect(panel()).toBeNull();
    await waitFor(() => expect(decision("NEW CONCEPT")).toBeEnabled());
  });
});

describe("Slow writes, unit switches, and unmount", () => {
  it("a slow write locks decisions and unit switches until the server answers", async () => {
    const b = backend();
    const slow = deferred();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", { slow });
    await renderQueue();
    fireEvent.click(decision("DISTINCT"));

    await screen.findByText(/Sending DISTINCT from concept #42 for unit #5…/);
    expect(screen.getByRole("button", { name: "skip →" })).toBeDisabled();
    for (const name of ["SAME → selected", "NEW CONCEPT", "INVALID"]) expect(decision(name)).toBeDisabled();
    fireEvent.click(decision("DISTINCT"));

    await act(async () => {
      slow.resolve({ status: 201, body: { id: 7 } });
    });
    await banner("status", "Recorded DISTINCT event");
    expect(screen.getByRole("button", { name: "skip →" })).toBeEnabled();
    expect(b.posts("/concept-distinctions")).toBe(1);
  });

  it("an unknown outcome stays with its unit: another unit is unaffected, and a late check lands on its own unit", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", "lost");
    const slowCheck = deferred();
    await renderQueue();
    // Delay this request's receipt lookup.
    let distinctionReads = 0;
    const original = globalThis.fetch;
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if ((init?.method ?? "GET") === "GET" && path.includes("/annotation-operations/")) {
        distinctionReads += 1;
        if (distinctionReads === 1) await slowCheck.promise;
      }
      return original(input, init);
    }) as typeof fetch;

    fireEvent.click(decision("DISTINCT"));
    await banner("alert", "Outcome unknown.");
    await screen.findByText("Checking the server for DISTINCT from concept #42 on unit #5…");

    fireEvent.click(screen.getByRole("button", { name: "skip →" }));
    await screen.findByText("Énoncé 6");
    expect(panel()).toBeNull();
    expect(screen.queryByText(/Outcome unknown/)).not.toBeInTheDocument();
    await waitFor(() => expect(decision("INVALID")).toBeEnabled());

    await act(async () => {
      slowCheck.resolve({ body: null });
    });
    expect(screen.queryByText(/Found on the server/)).not.toBeInTheDocument();
    expect(screen.getByText("Énoncé 6")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "← previous" }));
    await screen.findByText("Énoncé 5");
    await banner("status", /Found on the server: This request committed event #\d+/);
    expect(b.posts("/concept-distinctions")).toBe(1);
  });

  it("unmounting while a write is pending applies nothing afterwards", async () => {
    const b = backend();
    const slow = deferred();
    b.writeMode.set("POST /api/concepts", { slow });
    const { unmount } = await renderQueue();
    fireEvent.click(decision("NEW CONCEPT"));
    unmount();
    await act(async () => {
      slow.resolve("network-error");
    });
    expect(b.posts("/api/concepts")).toBe(1);
  });
});

describe("checkDecision for paths the queue cannot reach directly", () => {
  const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

  it("REASSIGN is found only when the membership moved to the requested concept", async () => {
    globalThis.fetch = vi.fn(async () => reply({ unit_id: 5, current_membership: { concept_id: 7, link_id: 2, updated_at: "t" } })) as unknown as typeof fetch;
    expect(await checkDecision({ kind: "same", unitId: 5, conceptId: 9, reassign: true }, null)).toEqual({
      found: false,
      text: "The unit's current SAME membership is concept #7, not #9.",
    });
    expect((await checkDecision({ kind: "same", unitId: 5, conceptId: 7, reassign: true }, null)).found).toBe(true);
  });

  it("NEW CONCEPT without SAME is found by its normalized identity in the catalog", async () => {
    globalThis.fetch = vi.fn(async () => reply({ concepts: [concept(8, "Cible  Nouvelle")] })) as unknown as typeof fetch;
    const identity = { target: "cible nouvelle", pedagogical_intent: "Grammar", scope: "", identity_features: {} };
    expect(await checkDecision({ kind: "new", unitId: 5, identity, seedAsSame: false }, null)).toEqual({
      found: true,
      text: "Concept #8 with this identity exists.",
    });
  });
});

describe("Evidence must match the decision, not just any change", () => {
  it("a relation that never arrived is not matched by an older stored event of the same kind", async () => {
    const b = backend();
    b.links.push({ id: 50, unit_id: 5, concept_id: 42, relation: "broader", status: "accepted" });
    b.writeMode.set("POST /api/knowledge-units/5/concept-links/relation", "not-sent");
    await renderQueue();
    fireEvent.click(decision("BROADER"));
    await waitFor(() => expect(panel()).toHaveTextContent("Receipt unknown."));
    expect(decision("NEW CONCEPT")).toBeDisabled();
  });

  it("NEW CONCEPT is not found when the unit was resolved elsewhere to a different identity", async () => {
    const b = backend();
    b.writeMode.set("POST /api/concepts", {
      notSentButElsewhere: () => b.memberships.set(5, { concept_id: 42, link_id: 77, updated_at: "t" }),
    });
    await renderQueue();
    fireEvent.change(screen.getByLabelText("target"), { target: { value: "cible éditée" } });
    fireEvent.click(decision("NEW CONCEPT"));
    await waitFor(() =>
      expect(panel()).toHaveTextContent('The unit now belongs to concept #42 ("cible 5"), whose identity differs from the draft.'),
    );
    expect(screen.getByText("Énoncé 5")).toBeInTheDocument();
  });

  it("a resolving decision found while viewing another unit removes that unit, not the one shown", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-links/same", "lost");
    const slowCheck = deferred();
    await renderQueue();
    let membershipReads = 0;
    const original = globalThis.fetch;
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if ((init?.method ?? "GET") === "GET" && path === "/api/knowledge-units/5/concept-membership") {
        membershipReads += 1;
        if (membershipReads === 1) await slowCheck.promise;
      }
      return original(input, init);
    }) as typeof fetch;

    fireEvent.click(decision("SAME → selected"));
    await screen.findByText("Checking the server for SAME → concept #42 on unit #5…");
    fireEvent.click(screen.getByRole("button", { name: "skip →" }));
    await screen.findByText("Énoncé 6");

    await act(async () => {
      slowCheck.resolve({ body: null });
    });
    await banner("status", "Unit #5: the server shows SAME → concept #42 is stored");
    expect(screen.getByText("Énoncé 6")).toBeInTheDocument();
    expect(screen.getByText("unit 1 of 1")).toBeInTheDocument();
  });
});

describe("FLH-032 recovery fixes", () => {
  const storageKey = "flh.annotation-operations.v1";
  const stored = () => JSON.parse(window.localStorage.getItem(storageKey) ?? '{"operations":[]}').operations;
  const keyOf = (call: [unknown, RequestInit?] | undefined) => new Headers(call?.[1]?.headers).get("Idempotency-Key");
  // Every POST seen by the outermost fetch, including ones a test holds.
  const keyedPosts = () => vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST");
  const postsTo = (suffix: string) => keyedPosts().filter(([url]) => String(url).endsWith(suffix)).length;

  // Wraps the fixture so the next POST to one path waits for an explicit reply.
  function holdNextPost(suffix: string) {
    const gate = deferred();
    const original = globalThis.fetch;
    let held = false;
    globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (!held && init?.method === "POST" && path.endsWith(suffix)) {
        held = true;
        const reply = await gate.promise;
        if (reply === "network-error") throw new TypeError("Failed to fetch");
        return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
      }
      return original(input, init);
    }) as unknown as typeof fetch;
    return gate;
  }

  it("F1: another tab's unresolved operation is a per-unit conflict, not a storage failure", async () => {
    const b = backend();
    await renderQueue();
    // Another tab saves an unresolved DISTINCT for unit 5 after this page loaded.
    const other = { kind: "distinct", unitId: 5, conceptId: 42, operationId: "11111111-2222-4333-8444-555555555555" };
    window.localStorage.setItem(storageKey, JSON.stringify({ version: 1, operations: [other] }));

    fireEvent.click(decision("RELATED"));
    await waitFor(() => expect(panel()).toHaveTextContent("this browser already has an unresolved DISTINCT from concept #42 saved for unit #5, probably from another tab"));
    expect(panel()).toHaveTextContent(`Saved operation ${other.operationId}`);
    expect(screen.queryByText(/Browser storage/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Recheck browser storage" })).not.toBeInTheDocument();
    expect(b.posts("/concept-links/relation")).toBe(0);
    expect(stored()).toEqual([other]);
    for (const name of ["SAME → selected", "NEW CONCEPT", "DISTINCT", "INVALID"]) expect(decision(name)).toBeDisabled();

    // An unrelated unit keeps keyed decisions.
    fireEvent.click(screen.getByRole("button", { name: "skip →" }));
    await screen.findByText("Énoncé 6");
    expect(panel()).toBeNull();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search existing concepts" }), { target: { value: "cible 5" } });
    fireEvent.click(await screen.findByRole("button", { name: "select this concept" }));
    await waitFor(() => expect(decision("DISTINCT")).toBeEnabled());
    fireEvent.click(decision("DISTINCT"));
    await banner("status", "Recorded DISTINCT");
    expect(b.distinctions.filter((d) => d.unit_id === 6)).toHaveLength(1);
    expect(keyOf(keyedPosts().at(-1))).not.toBe(other.operationId);

    // Back on unit 5 the kept operation is retried with its own key and payload.
    fireEvent.click(screen.getByRole("button", { name: "← previous" }));
    await screen.findByText("Énoncé 5");
    fireEvent.click(within(panel() as HTMLElement).getByRole("button", { name: "Retry saved operation" }));
    await banner("status", "Recorded DISTINCT");
    const retry = keyedPosts().at(-1)!;
    expect(keyOf(retry)).toBe(other.operationId);
    expect(retry[0]).toContain("/knowledge-units/5/concept-distinctions");
    expect(JSON.parse(String(retry[1]?.body))).toEqual({ concept_id: 42 });
    expect(b.posts("/concept-links/relation")).toBe(0);
    expect(stored()).toEqual([]);
  });

  it("F2: a definite rejection after leaving cleans up exactly that operation; a reload shows nothing unresolved", async () => {
    const b = backend();
    const first = await renderQueue();
    const gate = holdNextPost("/knowledge-units/5/concept-distinctions");
    fireEvent.click(decision("DISTINCT"));
    await waitFor(() => expect(stored()).toHaveLength(1));
    first.unmount();
    await act(async () => {
      gate.resolve({ status: 422, body: { error: "validation error" } });
    });
    expect(stored()).toEqual([]);
    await renderQueue();
    expect(panel()).toBeNull();
    expect(decision("DISTINCT")).toBeEnabled();
    expect(postsTo("/concept-distinctions")).toBe(1);
    expect(b.distinctions.filter((d) => d.unit_id === 5)).toHaveLength(1);
  });

  it("F2: an old operation's late rejection never clears a newer operation for the unit", async () => {
    backend();
    const first = await renderQueue();
    const gate = holdNextPost("/knowledge-units/5/concept-distinctions");
    fireEvent.click(decision("DISTINCT"));
    await waitFor(() => expect(stored()).toHaveLength(1));
    first.unmount();
    const newer = { kind: "relation", unitId: 5, conceptId: 42, relation: "broader", operationId: "99999999-8888-4777-8666-555555555555" };
    window.localStorage.setItem(storageKey, JSON.stringify({ version: 1, operations: [newer] }));
    await act(async () => {
      gate.resolve({ status: 422, body: { error: "validation error" } });
    });
    expect(stored()).toEqual([newer]);
  });

  it("F2: an unknown outcome after leaving stays recoverable with the original key and payload", async () => {
    const b = backend();
    const first = await renderQueue();
    const gate = holdNextPost("/knowledge-units/5/concept-distinctions");
    fireEvent.click(decision("DISTINCT"));
    await waitFor(() => expect(stored()).toHaveLength(1));
    const saved = stored()[0];
    first.unmount();
    await act(async () => {
      gate.resolve("network-error");
    });
    expect(stored()).toEqual([saved]);
    render(<StrictMode><ReviewQueue /></StrictMode>);
    await screen.findByText("Énoncé 5");
    await waitFor(() => expect(panel()).toHaveTextContent("Restored unresolved operation"));
    expect(decision("NEW CONCEPT")).toBeDisabled();
    fireEvent.click(within(panel() as HTMLElement).getByRole("button", { name: "Retry saved operation" }));
    await banner("status", "Recorded DISTINCT");
    expect(keyOf(keyedPosts().at(-1))).toBe(saved.operationId);
    expect(postsTo("/concept-distinctions")).toBe(2);
    expect(b.distinctions.filter((d) => d.unit_id === 5)).toHaveLength(2);
  });

  it("F3: storage failure disables keyed controls visibly; an explicit recheck re-enables them without sending", async () => {
    const b = backend();
    await renderQueue();
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    fireEvent.click(decision("DISTINCT"));
    await banner("alert", /Browser storage failed. Nothing was sent/);
    for (const name of ["DISTINCT", "BROADER", "NARROWER", "RELATED"]) expect(decision(name)).toBeDisabled();
    for (const name of ["SAME → selected", "NEW CONCEPT", "INVALID"]) expect(decision(name)).toBeEnabled();
    expect(screen.getByText(/disabled while browser storage cannot keep their operation keys/)).toBeInTheDocument();

    // Still failing: honest message, nothing sent.
    fireEvent.click(screen.getByRole("button", { name: "Recheck browser storage" }));
    await banner("alert", /still unavailable or unreadable/);
    expect(decision("DISTINCT")).toBeDisabled();

    setItem.mockRestore();
    fireEvent.click(screen.getByRole("button", { name: "Recheck browser storage" }));
    await banner("status", "Browser storage works again. Keyed decisions are enabled; nothing was sent.");
    expect(screen.queryByRole("button", { name: "Recheck browser storage" })).not.toBeInTheDocument();
    expect(b.posts("/concept-distinctions")).toBe(0);
    await waitFor(() => expect(decision("DISTINCT")).toBeEnabled());
    fireEvent.click(decision("DISTINCT"));
    await banner("status", "Recorded DISTINCT");
    expect(b.posts("/concept-distinctions")).toBe(1);
  });

  it("F3: an unreadable saved value on load keeps keyed controls disabled; recheck says reloading does not repair it", async () => {
    backend();
    window.localStorage.setItem(storageKey, "bad json");
    await renderQueue();
    await banner("alert", /Browser storage is unavailable or invalid/);
    expect(decision("BROADER")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Recheck browser storage" }));
    await banner("alert", /Reloading does not repair an unreadable saved value/);
    expect(window.localStorage.getItem(storageKey)).toBe("bad json");
  });

  it("F3: a failed cleanup after commit is retried by the recheck, leaving nothing unresolved", async () => {
    const b = backend();
    await renderQueue();
    const realSet = Storage.prototype.setItem;
    let writes = 0;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, k: string, v: string) {
      writes += 1;
      if (writes > 1) throw new Error("quota");
      realSet.call(this, k, v);
    });
    fireEvent.click(decision("DISTINCT"));
    await banner("alert", /Request committed, but browser storage cleanup failed/);
    await banner("status", "Recorded DISTINCT");
    expect(stored()).toHaveLength(1);
    vi.mocked(Storage.prototype.setItem).mockRestore();
    fireEvent.click(screen.getByRole("button", { name: "Recheck browser storage" }));
    await banner("status", "Browser storage works again.");
    expect(stored()).toEqual([]);
    expect(panel()).toBeNull();
    expect(b.posts("/concept-distinctions")).toBe(1);
  });
});
