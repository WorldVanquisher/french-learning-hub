// Speaking practice overview exactly as the backend answered GET /speaking/practice
// in the part-5 end-to-end walk (docs/validation/FLH-152-PART5-SPEAKING.md): one
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
        "id": 1,
        "prompt_id": "sp-invitation-reponse",
        "title": "Répondre à une invitation",
        "situation": "Votre amie Léa vous a laissé un message : elle organise un pique-nique samedi prochain à midi, au parc des Tilleuls, et elle vous invite. Rappelez-la et laissez-lui un message vocal.",
        "requirements": [
          "Remerciez Léa pour l'invitation.",
          "Dites si vous venez et à quelle heure vous arriverez.",
          "Proposez d'apporter quelque chose.",
          "Posez une question sur l'organisation."
        ],
        "seconds_min": 30,
        "seconds_max": 90,
        "created_at": "2026-11-17T23:01:06.417412544Z",
        "prompt_set": "flh_speaking_prompts_v1",
        "content_fingerprint": "f9a94e5fce7b8a9cb6b46601fe2d23d22c4fa0e69be97d1ee54654f308dd6cec",
        "pack_status": "current"
      },
      "last_activity_at": "2026-11-17T23:01:06.468496443Z",
      "latest": {
        "take_id": 3,
        "take_number": 3,
        "state": "transcript_to_confirm",
        "transcript_versions": 0,
        "latest_version": null,
        "feedback_id": null,
        "feedback_rating": null,
        "improvements": 0,
        "activity_at": "2026-11-17T23:01:06.468496443Z",
        "take_created_at": "2026-11-17T23:01:06.455532465Z",
        "audio_source": "file",
        "transcript_origin": null
      },
      "takes": 3
    }
  ],
  "generated_at": "2026-11-17T23:01:06.470377049Z",
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
      "priority": 2,
      "prompt_id": "sp-invitation-reponse",
      "reason": "confirm_transcript",
      "since": "2026-11-17T23:01:06.468496443Z",
      "state": "transcript_to_confirm",
      "take_id": 3,
      "take_number": 3,
      "title": "Répondre à une invitation"
    },
    {
      "exercise_id": null,
      "improvements": 0,
      "priority": 7,
      "prompt_id": "sp-demande-renseignements",
      "reason": "not_started",
      "since": null,
      "state": null,
      "take_id": null,
      "take_number": null,
      "title": "Demander des renseignements"
    },
    {
      "exercise_id": null,
      "improvements": 0,
      "priority": 7,
      "prompt_id": "sp-changement-programme",
      "reason": "not_started",
      "since": null,
      "state": null,
      "take_id": null,
      "take_number": null,
      "title": "Expliquer un changement de programme"
    }
  ],
  "schema_version": "speaking_practice_v1",
  "summary": {
    "awaiting_feedback": 1,
    "awaiting_transcript": 1,
    "completed": 1,
    "exercises_completed": 1,
    "failed": 0,
    "in_progress": 0,
    "last_completed_at": "2026-11-17T23:01:06.441956045Z",
    "prompts": 3,
    "started": 1,
    "takes": 3,
    "unknown": 0
  }
};
