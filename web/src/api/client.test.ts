import { describe, expect, it, vi } from "vitest";
import * as api from "./client";
import { ApiError } from "./client";

// A tiny fetch stub that records the request and returns a canned JSON response.
function stubFetch(status: number, body: unknown) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const impl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    return new Response(body === undefined ? "" : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return { impl, calls };
}

describe("api client request shapes", () => {
  it("lists reviewable units via GET /api/reviewable-units with entry scope", async () => {
    const { impl, calls } = stubFetch(200, { reviewable_units: [{ unit_id: 5 }] });
    const units = await api.listReviewableUnits(42, impl);
    expect(calls[0].url).toBe("/api/reviewable-units?entry_id=42");
    expect(calls[0].init.method).toBe("GET");
    expect(units).toHaveLength(1);
    expect(units[0].unit_id).toBe(5);
  });

  it("lists the existing concept catalog via GET /api/concepts", async () => {
    const { impl, calls } = stubFetch(200, { concepts: [{ id: 7, target: "être" }] });
    const concepts = await api.listConcepts(impl);
    expect(calls[0].url).toBe("/api/concepts");
    expect(calls[0].init.method).toBe("GET");
    expect(concepts).toHaveLength(1);
    expect(concepts[0].id).toBe(7);
  });

  it("lists effective annotations via the read-only collection endpoint", async () => {
    const { impl, calls } = stubFetch(200, {
      effective_annotations: [{ unit: { id: 5 }, snapshot: { unit_id: 5, status: "unresolved" } }],
    });
    const annotations = await api.listEffectiveAnnotations(impl);
    expect(calls[0].url).toBe("/api/effective-annotations");
    expect(calls[0].init.method).toBe("GET");
    expect(annotations[0].unit.id).toBe(5);
  });

  it("gets the typed annotation quality report from its read-only path", async () => {
    const { impl, calls } = stubFetch(200, {
      schema_version: "concept_annotation_quality_report_v1",
      dataset_schema_version: "concept_annotation_dataset_v1",
      valid: true,
      error_count: 0,
      warning_count: 1,
      summary: { total_records: 8, total_entries: 5 },
      label_inventory: { human_same_records: 3 },
      provenance: {},
      leakage_risk: {},
      issues: [],
    });

    const report = await api.getAnnotationDatasetQuality(impl);

    expect(calls[0].url).toBe("/api/annotation-dataset/v1/quality");
    expect(calls[0].init.method).toBe("GET");
    expect(report.valid).toBe(true);
    expect(report.summary.total_records).toBe(8);
    expect(report.label_inventory.human_same_records).toBe(3);
  });

  it("gets the typed retrieval comparison without changing backend row order", async () => {
    const { impl, calls } = stubFetch(200, {
      schema_version: "concept_retrieval_comparison_v1",
      state: "evaluated",
      dataset_valid: true,
      candidate_universe: { concepts: 12 },
      evaluation_samples: { eligible_samples: 4 },
      retrievers: [
        {
          retriever: "exact_signature_retriever_v1",
          state: "evaluated",
          metrics: { recall_at_1: 0.25, recall_at_3: 0.5, recall_at_5: 0.75, mrr: 0.4 },
        },
        {
          retriever: "embedding_retriever_v1",
          state: "unavailable",
          metrics: { recall_at_1: null, recall_at_3: null, recall_at_5: null, mrr: null },
        },
      ],
    });

    const report = await api.getRetrievalComparison(impl);

    expect(calls[0].url).toBe("/api/retrieval-comparison/v1");
    expect(calls[0].init.method).toBe("GET");
    expect(report.retrievers.map((row) => row.retriever)).toEqual([
      "exact_signature_retriever_v1",
      "embedding_retriever_v1",
    ]);
    expect(report.retrievers[1].metrics.mrr).toBeNull();
  });

  it("propagates experiment endpoint errors through the existing ApiError", async () => {
    const { impl } = stubFetch(502, { error: "embedding provider unavailable" });

    await expect(api.getRetrievalComparison(impl)).rejects.toMatchObject({
      name: "ApiError",
      status: 502,
      message: "embedding provider unavailable",
    });
  });

  it("gets one effective annotation via its read-only unit endpoint", async () => {
    const { impl, calls } = stubFetch(200, {
      unit: { id: 5 },
      snapshot: { unit_id: 5, status: "resolved" },
    });
    const annotation = await api.getEffectiveAnnotation(5, impl);
    expect(calls[0].url).toBe("/api/knowledge-units/5/effective-annotation");
    expect(calls[0].init.method).toBe("GET");
    expect(annotation.snapshot.status).toBe("resolved");
  });

  it("reads current membership from the projection endpoint (never history)", async () => {
    const { impl, calls } = stubFetch(200, { unit_id: 7, current_membership: null });
    const env = await api.getCurrentMembership(7, impl);
    expect(calls[0].url).toBe("/api/knowledge-units/7/concept-membership");
    expect(calls[0].init.method).toBe("GET");
    expect(env.current_membership).toBeNull();
  });

  it("resolveSame POSTs concept_id to the same-link endpoint", async () => {
    const { impl, calls } = stubFetch(201, { id: 10, relation: "same", status: "accepted" });
    await api.resolveSame(7, 42, impl);
    expect(calls[0].url).toBe("/api/knowledge-units/7/concept-links/same");
    expect(calls[0].init.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ concept_id: 42 });
  });

  it("reassignSame PUTs to the concept-membership endpoint (explicit correction)", async () => {
    const { impl, calls } = stubFetch(200, { id: 11, relation: "same", status: "accepted" });
    await api.reassignSame(7, 99, impl);
    expect(calls[0].url).toBe("/api/knowledge-units/7/concept-membership");
    expect(calls[0].init.method).toBe("PUT");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ concept_id: 99 });
  });

  it("createConcept POSTs identity + seed flags to /api/concepts", async () => {
    const { impl, calls } = stubFetch(201, { concept: { id: 1 }, link: null });
    await api.createConcept(
      { target: "t", pedagogical_intent: "grammar", scope: "", identity_features: {} },
      7,
      true,
      impl,
    );
    expect(calls[0].url).toBe("/api/concepts");
    expect(calls[0].init.method).toBe("POST");
    const sent = JSON.parse(String(calls[0].init.body));
    expect(sent.seed_unit_id).toBe(7);
    expect(sent.link_seed_as_same).toBe(true);
    expect(sent.identity.target).toBe("t");
  });

  it("recordRelation POSTs relation + concept_id to the relation endpoint", async () => {
    const { impl, calls } = stubFetch(201, { id: 12, relation: "broader", status: "accepted" });
    await api.recordRelation(7, 42, "broader", impl);
    expect(calls[0].url).toBe("/api/knowledge-units/7/concept-links/relation");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ concept_id: 42, relation: "broader" });
  });

  it("rejectSameMembership POSTs to the membership-level reject endpoint", async () => {
    const { impl, calls } = stubFetch(200, { unit_id: 7, current_membership: null, link: { id: 13 } });
    const res = await api.rejectSameMembership(7, impl);
    expect(calls[0].url).toBe("/api/knowledge-units/7/concept-membership/reject");
    expect(calls[0].init.method).toBe("POST");
    expect(res.current_membership).toBeNull();
  });

  it("markUnitInvalid POSTs to the unit-level invalid endpoint (no membership required)", async () => {
    const { impl, calls } = stubFetch(200, {
      unit_id: 7,
      invalid: true,
      current_membership: null,
      judgment: { id: 5, unit_id: 7, judgment: "invalid", decision_source: "human", note: "", evidence: "{}", created_at: "t" },
    });
    const res = await api.markUnitInvalid(7, impl);
    expect(calls[0].url).toBe("/api/knowledge-units/7/invalid");
    expect(calls[0].init.method).toBe("POST");
    expect(res.invalid).toBe(true);
    expect(res.judgment?.judgment).toBe("invalid");
  });

  it("restoreUnit POSTs to the invalid/restore endpoint", async () => {
    const { impl, calls } = stubFetch(200, { unit_id: 7, invalid: false, current_membership: null, judgment: { judgment: "restored" } });
    const res = await api.restoreUnit(7, impl);
    expect(calls[0].url).toBe("/api/knowledge-units/7/invalid/restore");
    expect(calls[0].init.method).toBe("POST");
    expect(res.invalid).toBe(false);
  });

  it("getUnitInvalid GETs the invalid read model with history", async () => {
    const { impl, calls } = stubFetch(200, { unit_id: 7, invalid: false, history: [{ judgment: "restored" }, { judgment: "invalid" }] });
    const env = await api.getUnitInvalid(7, impl);
    expect(calls[0].url).toBe("/api/knowledge-units/7/invalid");
    expect(calls[0].init.method).toBe("GET");
    expect(env.history).toHaveLength(2);
  });

  it("recordDistinction POSTs concept_id to the concept-distinctions endpoint", async () => {
    const { impl, calls } = stubFetch(201, { id: 3, unit_id: 7, concept_id: 42, decision_source: "human", resolver_version: "concept_resolver_v1", evidence: "{}", created_at: "t" });
    const d = await api.recordDistinction(7, 42, impl);
    expect(calls[0].url).toBe("/api/knowledge-units/7/concept-distinctions");
    expect(calls[0].init.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ concept_id: 42 });
    expect(d.concept_id).toBe(42);
  });

  it("maps a 409 into an ApiError flagged as a conflict, preferring backend error text", async () => {
    const { impl } = stubFetch(409, { error: "unit already has a current SAME membership to another concept" });
    await expect(api.resolveSame(7, 42, impl)).rejects.toMatchObject({ status: 409 });
    try {
      await api.resolveSame(7, 42, impl);
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).isConflict).toBe(true);
      expect((e as ApiError).message).toContain("already has a current SAME");
    }
  });

  it("maps a 404 into an ApiError flagged as not-found", async () => {
    const { impl } = stubFetch(404, { error: "knowledge unit not found" });
    try {
      await api.getCurrentMembership(999, impl);
      throw new Error("expected rejection");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).isNotFound).toBe(true);
    }
  });
});
