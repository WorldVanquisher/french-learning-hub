// Speaking practice overview exactly as the backend answered GET /speaking/practice
// in the end-to-end walk (re-recorded for docs/validation/SPEAKING-PRACTICE-QUEUE.md): one
// exercise with three takes (one completed, one typed and waiting for feedback, one
// machine transcript to check after an unknown outcome and an explicit retry) and
// two prompts not started, against a loopback fake provider. Synthetic, no learner
// data. Typed against the wire types, so contract drift fails the typecheck.
import type { SpeakingPractice } from "../types/speaking";

export const practiceFromWalk: SpeakingPractice = {
  "exercises": [
    {
      "completed": 1,
      "exercise": {
        "content_fingerprint": "f9a94e5fce7b8a9cb6b46601fe2d23d22c4fa0e69be97d1ee54654f308dd6cec",
        "created_at": "2026-11-18T07:05:19.333001964Z",
        "id": 1,
        "pack_status": "current",
        "prompt_id": "sp-invitation-reponse",
        "prompt_set": "flh_speaking_prompts_v1",
        "requirements": [
          "Remerciez Léa pour l'invitation.",
          "Dites si vous venez et à quelle heure vous arriverez.",
          "Proposez d'apporter quelque chose.",
          "Posez une question sur l'organisation."
        ],
        "seconds_max": 90,
        "seconds_min": 30,
        "situation": "Votre amie Léa vous a laissé un message : elle organise un pique-nique samedi prochain à midi, au parc des Tilleuls, et elle vous invite. Rappelez-la et laissez-lui un message vocal.",
        "title": "Répondre à une invitation"
      },
      "last_activity_at": "2026-11-18T07:05:19.38493871Z",
      "latest": {
        "activity_at": "2026-11-18T07:05:19.38493871Z",
        "audio_source": "file",
        "feedback_id": null,
        "feedback_rating": null,
        "improvements": 0,
        "latest_version": null,
        "state": "transcript_to_confirm",
        "take_created_at": "2026-11-18T07:05:19.371798955Z",
        "take_id": 3,
        "take_number": 3,
        "transcript_origin": null,
        "transcript_versions": 0
      },
      "takes": 3
    }
  ],
  "generated_at": "2026-11-18T07:05:19.387271897Z",
  "providers": {
    "feedback": {
      "enabled": true,
      "name": "openai:stub-model:speaking_feedback_v1"
    },
    "transcription": {
      "enabled": true,
      "name": "openai:stub-transcribe:speaking_transcription_v1"
    }
  },
  "queue": [
    {
      "exercise_id": 1,
      "improvements": 0,
      "pack_status": "current",
      "priority": 2,
      "prompt_id": "sp-invitation-reponse",
      "reason": "confirm_transcript",
      "request": null,
      "request_enabled": false,
      "since": "2026-11-18T07:05:19.38493871Z",
      "state": "transcript_to_confirm",
      "take_id": 3,
      "take_number": 3,
      "title": "Répondre à une invitation"
    },
    {
      "exercise_id": null,
      "improvements": 0,
      "pack_status": null,
      "priority": 9,
      "prompt_id": "sp-demande-renseignements",
      "reason": "not_started",
      "request": null,
      "request_enabled": false,
      "since": null,
      "state": null,
      "take_id": null,
      "take_number": null,
      "title": "Demander des renseignements"
    },
    {
      "exercise_id": null,
      "improvements": 0,
      "pack_status": null,
      "priority": 9,
      "prompt_id": "sp-changement-programme",
      "reason": "not_started",
      "request": null,
      "request_enabled": false,
      "since": null,
      "state": null,
      "take_id": null,
      "take_number": null,
      "title": "Expliquer un changement de programme"
    }
  ],
  "resume": {
    "exercise_id": 1,
    "improvements": 0,
    "pack_status": "current",
    "priority": 2,
    "prompt_id": "sp-invitation-reponse",
    "reason": "confirm_transcript",
    "request": null,
    "request_enabled": false,
    "since": "2026-11-18T07:05:19.38493871Z",
    "state": "transcript_to_confirm",
    "take_id": 3,
    "take_number": 3,
    "title": "Répondre à une invitation"
  },
  "schema_version": "speaking_practice_v1",
  "summary": {
    "awaiting_feedback": 1,
    "awaiting_transcript": 1,
    "completed": 1,
    "exercises_completed": 1,
    "failed": 0,
    "in_progress": 0,
    "last_completed_at": "2026-11-18T07:05:19.358585066Z",
    "prompts": 3,
    "started": 1,
    "takes": 3,
    "unknown": 0
  }
};
