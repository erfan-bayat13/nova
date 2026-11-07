// LFM3-Omni on the phone: mirrors the realtime path of llama.cpp's server (tools/server/server-realtime.cpp).
//
// Turn = [system header on the first turn] + "<|im_start|>user\n" + audio rows (mtmd audio stream, decoded as
// embeddings) + "<|im_end|>\n<|im_start|>assistant\n" (the gen-audio prompt) + generated reply, then the
// footer "<|im_end|>\n" goes in before the next user turn.

#include <llama/llama.h>
#include <llama/mtmd.h>
#include <llama/mtmd-helper.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "NovaBridge.h"

namespace {

struct Engine {
    llama_model *            model = nullptr;
    llama_context *          ctx   = nullptr;
    mtmd_context *           mctx  = nullptr;
    mtmd_helper_gen_audio *  gen   = nullptr;
    const llama_vocab *      vocab = nullptr;
    int32_t n_ctx   = 0;
    int32_t n_embd  = 0;      // decoder hidden size (h_state)
    int32_t n_embd_inp = 0;
    int32_t n_batch = 512;
    int32_t n_past  = 0;
    int     n_turns = 0;
    std::string system;
    std::atomic<bool> cancel{false};
};

void set_err(char * err, size_t len, const char * msg) {
    if (err && len) snprintf(err, len, "%s", msg);
}

bool decode(Engine * e, const llama_token * tokens, const float * rows, int32_t n, bool logits_last) {
    if (e->n_past + n >= e->n_ctx) return false;
    for (int32_t i0 = 0; i0 < n; i0 += e->n_batch) {
        const int32_t n_cur = std::min(e->n_batch, n - i0);
        llama_batch b = llama_batch_init(n_cur, rows ? e->n_embd_inp : 0, 1);
        for (int32_t i = 0; i < n_cur; i++) {
            if (rows) memcpy(b.embd + (size_t) i * e->n_embd_inp, rows + (size_t) (i0 + i) * e->n_embd_inp, e->n_embd_inp * sizeof(float));
            else      b.token[i] = tokens[i0 + i];
            b.pos[i]       = e->n_past + i0 + i;
            b.n_seq_id[i]  = 1;
            b.seq_id[i][0] = 0;
            b.logits[i]    = logits_last && i0 + i == n - 1;
        }
        b.n_tokens = n_cur;
        const int ret = llama_decode(e->ctx, b);
        llama_batch_free(b);
        if (ret != 0) return false;
    }
    e->n_past += n;
    return true;
}

bool decode_text(Engine * e, const std::string & text) {
    std::vector<llama_token> toks(text.size() + 8);
    int32_t n = llama_tokenize(e->vocab, text.c_str(), (int32_t) text.size(), toks.data(), (int32_t) toks.size(), false, true);
    if (n < 0) {
        toks.resize(-n);
        n = llama_tokenize(e->vocab, text.c_str(), (int32_t) text.size(), toks.data(), (int32_t) toks.size(), false, true);
    }
    if (n <= 0) return n == 0;
    return decode(e, toks.data(), nullptr, n, false);
}

void clear_context(Engine * e) {
    llama_memory_clear(llama_get_memory(e->ctx), true);
    e->n_past  = 0;
    e->n_turns = 0;
}

// the model's own position is the truth after the gen-audio pipeline decoded on its own
void sync_past(Engine * e) {
    e->n_past = llama_memory_seq_pos_max(llama_get_memory(e->ctx), 0) + 1;
}

} // namespace

extern "C" {

NovaEngineRef nova_engine_load(const char * model_path, const char * mmproj_path, int n_ctx,
                               const char * system_prompt, char * err, size_t err_len) {
    auto * e = new Engine();
    e->system = system_prompt ? system_prompt : "";
    e->n_ctx  = n_ctx;

    llama_backend_init();
    llama_model_params mp = llama_model_default_params();
    mp.n_gpu_layers = 99;
    mp.load_mode    = LLAMA_LOAD_MODE_MMAP;
    e->model = llama_model_load_from_file(model_path, mp);
    if (!e->model) { set_err(err, err_len, "could not load the model file"); nova_engine_free(e); return nullptr; }
    e->vocab = llama_model_get_vocab(e->model);

    llama_context_params cp = llama_context_default_params();
    cp.n_ctx           = (uint32_t) n_ctx;
    cp.n_batch         = (uint32_t) e->n_batch;
    cp.n_ubatch        = (uint32_t) e->n_batch;
    cp.n_threads       = 4;
    cp.n_threads_batch = 4;
    cp.embeddings      = true;
    e->ctx = llama_init_from_model(e->model, cp);
    if (!e->ctx) { set_err(err, err_len, "not enough memory for the model context"); nova_engine_free(e); return nullptr; }
    llama_set_embeddings(e->ctx, true);
    e->n_ctx      = (int32_t) llama_n_ctx(e->ctx);
    e->n_batch    = (int32_t) llama_n_batch(e->ctx);
    e->n_embd     = llama_model_n_embd(e->model);
    e->n_embd_inp = llama_model_n_embd_inp(e->model);

    mtmd_context_params mpar = mtmd_context_params_default();
    mpar.use_gpu       = true;
    mpar.print_timings = false;
    mpar.n_threads     = 4;
    e->mctx = mtmd_init_from_file(mmproj_path, e->model, mpar);
    if (!e->mctx) { set_err(err, err_len, "could not load the audio projector"); nova_engine_free(e); return nullptr; }
    if (mtmd_get_audio_sample_rate(e->mctx) != 16000 || !mtmd_support_audio_stream(e->mctx)) {
        set_err(err, err_len, "the projector does not take 16 kHz audio"); nova_engine_free(e); return nullptr;
    }
    if (mtmd_gen_audio_get_info(e->mctx).type != MTMD_GEN_AUDIO_TYPE_LFM3A) {
        set_err(err, err_len, "the model cannot speak (not LFM3-Audio)"); nova_engine_free(e); return nullptr;
    }
    e->gen = mtmd_helper_gen_audio_init(e->ctx, e->mctx);
    if (!e->gen) { set_err(err, err_len, "could not start the speech generator"); nova_engine_free(e); return nullptr; }
    return e;
}

void nova_engine_free(NovaEngineRef h) {
    auto * e = (Engine *) h;
    if (!e) return;
    if (e->gen)   mtmd_helper_gen_audio_free(e->gen);
    if (e->mctx)  mtmd_free(e->mctx);
    if (e->ctx)   llama_free(e->ctx);
    if (e->model) llama_model_free(e->model);
    delete e;
}

void nova_engine_cancel(NovaEngineRef h) { if (h) ((Engine *) h)->cancel = true; }

void nova_engine_reset(NovaEngineRef h) { if (h) clear_context((Engine *) h); }

int nova_engine_respond(NovaEngineRef h, const int16_t * pcm16k, size_t n_samples, double max_audio_seconds,
                        NovaEmitFn emit, void * user, int64_t * out_audio_samples, char * err, size_t err_len) {
    auto * e = (Engine *) h;
    if (out_audio_samples) *out_audio_samples = 0;
    if (!e) { set_err(err, err_len, "engine not loaded"); return -1; }
    // a cancel that arrived before this turn started belongs to the previous one
    e->cancel = false;

    const double in_seconds = (double) n_samples / 16000.0;
    // ~12.5 audio frames per second in, up to ~12.5 per second out, plus text and headers
    const int32_t need = (int32_t) (in_seconds * 13.0) + (int32_t) (max_audio_seconds * 14.0) + 160 + (int32_t) e->system.size() / 3;
    if (e->n_turns > 0 && e->n_past + need >= e->n_ctx) clear_context(e);   // rotate before the context fills
    if (e->n_past + need >= e->n_ctx && e->n_turns == 0) {
        // a single huge input: keep only what fits
        const double fit = std::max(0.5, (double) (e->n_ctx - 160 - (int32_t) e->system.size() / 3) / 13.0 - max_audio_seconds * 14.0 / 13.0);
        n_samples = std::min(n_samples, (size_t) (fit * 16000.0));
        pcm16k    = pcm16k + 0;   // keep the start; the tail is dropped
    }

    // 1. turn header (system prompt on the first turn of a context)
    std::string header;
    if (e->n_turns == 0) {
        header = "<|startoftext|><|im_start|>system\n" + e->system + "<|im_end|>\n<|im_start|>user\n";
    } else {
        header = "<|im_end|>\n<|im_start|>user\n";   // closes the previous assistant turn, opens the user turn
    }
    if (!decode_text(e, header)) { clear_context(e); set_err(err, err_len, "context overflow"); return -2; }

    // 2. the user's audio, as embedding rows
    {
        std::vector<float> f(n_samples);
        for (size_t i = 0; i < n_samples; i++) f[i] = pcm16k[i] / 32768.0f;
        mtmd_audio_stream * stream = mtmd_audio_stream_init(e->mctx, mtmd_audio_stream_params_default());
        if (!stream) { set_err(err, err_len, "audio stream failed"); return -3; }
        bool ok = true;
        // feed in ~1 s pieces so a cancel is noticed between encoder calls
        const size_t piece = 16000;
        for (size_t off = 0; off < f.size() && ok; off += piece) {
            if (e->cancel) { mtmd_audio_stream_free(stream); return 1; }
            mtmd_audio_stream_push(stream, f.data() + off, std::min(piece, f.size() - off));
            int32_t n;
            while ((n = mtmd_audio_stream_step(stream, LLAMA_TOKEN_NULL)) > 0 && ok) {
                ok = decode(e, nullptr, mtmd_audio_stream_get_output_embd(stream), n, false);
            }
            if (n == -2) ok = false;
        }
        if (ok && !e->cancel) {
            mtmd_audio_stream_flush(stream, true);
            int32_t n;
            while ((n = mtmd_audio_stream_step(stream, LLAMA_TOKEN_NULL)) > 0 && ok) {
                ok = decode(e, nullptr, mtmd_audio_stream_get_output_embd(stream), n, false);
            }
            if (n == -2) ok = false;
        }
        mtmd_audio_stream_free(stream);
        if (!ok)       { clear_context(e); set_err(err, err_len, "could not process the audio"); return -4; }
        if (e->cancel) { sync_past(e); e->n_turns++; return 1; }
    }

    // 3. start the response: assistant header, interleaved text + speech
    const std::string prompt = "<|im_end|>\n<|im_start|>assistant\n";
    mtmd_helper_gen_audio_inp inp = mtmd_helper_gen_audio_inp_default();
    inp.stream     = true;
    inp.seq_id     = 0;
    inp.prompt     = prompt.c_str();
    inp.prompt_len = prompt.size();
    inp.n_past     = e->n_past;
    inp.out_mode   = MTMD_HELPER_GEN_AUDIO_OUT_MIXED;
    inp.out_type   = MTMD_HELPER_GEN_AUDIO_OUTTYPE_PCM;
    inp.seed       = UINT32_MAX;
    if (mtmd_helper_gen_audio_set_input(e->gen, &inp) != 0) { clear_context(e); set_err(err, err_len, "could not start the reply"); return -5; }

    size_t n_bias = 0;
    const llama_logit_bias * bias = mtmd_helper_gen_audio_get_logit_bias(e->gen, &n_bias);
    llama_sampler * smpl = llama_sampler_chain_init(llama_sampler_chain_default_params());
    if (n_bias > 0) llama_sampler_chain_add(smpl, llama_sampler_init_logit_bias(llama_vocab_n_tokens(e->vocab), (int32_t) n_bias, bias));
    llama_sampler_chain_add(smpl, llama_sampler_init_top_k(50));
    llama_sampler_chain_add(smpl, llama_sampler_init_temp(0.5f));
    llama_sampler_chain_add(smpl, llama_sampler_init_dist(LLAMA_DEFAULT_SEED));

    int32_t ret;
    while ((ret = mtmd_helper_gen_audio_step_prompt(e->gen, e->n_batch)) > 0) {
        if (e->cancel) { llama_sampler_free(smpl); sync_past(e); e->n_turns++; return 1; }
    }
    if (ret < 0) { llama_sampler_free(smpl); clear_context(e); set_err(err, err_len, "could not start the reply"); return -5; }

    std::vector<float> h_state(e->n_embd);
    {
        const float * h = llama_get_embeddings_ith(e->ctx, -1);
        if (!h) { llama_sampler_free(smpl); clear_context(e); set_err(err, err_len, "no hidden state"); return -6; }
        h_state.assign(h, h + e->n_embd);
    }

    // 4. generation loop
    const int64_t max_samples = (int64_t) (max_audio_seconds * 24000.0);
    int64_t total = 0;
    int     n_decoded = 0;
    const int max_steps = (int) (max_audio_seconds * 12.5 * 3) + 600;
    llama_token sampled = LLAMA_TOKEN_NULL;
    bool cancelled = false, failed = false;
    auto sample_next = [&]() {
        sampled = LLAMA_TOKEN_NULL;
        if (mtmd_helper_gen_audio_next_is_text(e->gen)) sampled = llama_sampler_sample(smpl, e->ctx, -1);
    };
    sample_next();

    std::vector<int16_t> out;
    for (;;) {
        if (e->cancel) { cancelled = true; break; }
        bool stop = false;
        const float * h_next = nullptr;
        if (mtmd_helper_gen_audio_step_gen(e->gen, sampled, h_state.data(), &h_next, &stop) != 0) { failed = true; break; }
        if (h_next) h_state.assign(h_next, h_next + e->n_embd);
        n_decoded++;

        const bool ctx_full = llama_memory_seq_pos_max(llama_get_memory(e->ctx), 0) + 2 >= e->n_ctx;
        const bool done = stop || ctx_full || total >= max_samples || n_decoded >= max_steps;
        if (!done) sample_next();
        if (done) mtmd_helper_gen_audio_flush(e->gen);

        int32_t rate = 0; const char * data = nullptr; size_t len = 0;
        if (mtmd_helper_gen_audio_get_output(e->gen, &rate, &data, &len, nullptr) == 0 && len > 0) {
            const size_t n = len / sizeof(float);
            const float * f = (const float *) data;
            out.resize(n);
            for (size_t i = 0; i < n; i++) {
                const float v = std::max(-1.0f, std::min(1.0f, f[i]));
                out[i] = (int16_t) std::lround(v * 32767.0f);
            }
            total += (int64_t) n;
            if (emit) emit(out.data(), n, user);
        }
        if (done) break;
    }
    llama_sampler_free(smpl);
    sync_past(e);
    e->n_turns++;
    if (out_audio_samples) *out_audio_samples = total;
    if (failed) { clear_context(e); set_err(err, err_len, "reply generation failed"); return -7; }
    return cancelled ? 1 : 0;
}

} // extern "C"
