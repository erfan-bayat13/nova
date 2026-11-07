// C-callable bridge over llama.cpp + mtmd (LFM3-Omni speech in, speech out). Used by LlamaEngine.swift.
#ifndef NOVA_BRIDGE_H
#define NOVA_BRIDGE_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef void * NovaEngineRef;

// Called with PCM16 mono 24 kHz samples as they are made. Runs on the generating thread.
typedef void (*NovaEmitFn)(const int16_t * samples, size_t count, void * user);

// Loads model + projector (Metal, mmap). Returns NULL and fills err on failure.
NovaEngineRef nova_engine_load(const char * model_path, const char * mmproj_path, int n_ctx,
                               const char * system_prompt, char * err, size_t err_len);

void nova_engine_free(NovaEngineRef e);

// Thread-safe: makes a running (or the next) nova_engine_respond stop quickly. Cleared at the start of respond.
void nova_engine_cancel(NovaEngineRef e);

// Forgets the conversation (keeps the model loaded).
void nova_engine_reset(NovaEngineRef e);

// One turn. pcm16k: PCM16 mono 16 kHz. Returns 0 ok, 1 cancelled, <0 error (err filled).
// out_audio_samples gets the number of 24 kHz samples emitted. max_audio_seconds caps the reply.
int nova_engine_respond(NovaEngineRef e, const int16_t * pcm16k, size_t n_samples, double max_audio_seconds,
                        NovaEmitFn emit, void * user, int64_t * out_audio_samples, char * err, size_t err_len);

#ifdef __cplusplus
}
#endif
#endif
