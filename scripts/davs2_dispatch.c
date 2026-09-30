/* 为独立的 8bit/10bit 静态库提供兼容 davs2 的分发接口。 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "davs2.h"

#define DECLARE_BACKEND(prefix) \
    extern void *prefix##davs2_decoder_open(davs2_param_t *); \
    extern int prefix##davs2_decoder_send_packet(void *, davs2_packet_t *); \
    extern int prefix##davs2_decoder_recv_frame(void *, davs2_seq_info_t *, davs2_picture_t *); \
    extern int prefix##davs2_decoder_flush(void *, davs2_seq_info_t *, davs2_picture_t *); \
    extern void prefix##davs2_decoder_frame_unref(void *, davs2_picture_t *); \
    extern void prefix##davs2_decoder_close(void *)

DECLARE_BACKEND(lumora8_);
DECLARE_BACKEND(lumora10_);

typedef struct {
    void *(*open)(davs2_param_t *);
    int (*send)(void *, davs2_packet_t *);
    int (*recv)(void *, davs2_seq_info_t *, davs2_picture_t *);
    int (*flush)(void *, davs2_seq_info_t *, davs2_picture_t *);
    void (*unref)(void *, davs2_picture_t *);
    void (*close)(void *);
} backend_api;

#define BACKEND(prefix) { prefix##davs2_decoder_open, prefix##davs2_decoder_send_packet, \
    prefix##davs2_decoder_recv_frame, prefix##davs2_decoder_flush, \
    prefix##davs2_decoder_frame_unref, prefix##davs2_decoder_close }

static const backend_api api8 = BACKEND(lumora8_);
static const backend_api api10 = BACKEND(lumora10_);

typedef struct {
    davs2_param_t param;
    const backend_api *api;
    void *decoder;
    unsigned char *pending;
    int pending_size;
    int depth;
    int failed;
    int64_t pts, dts;
} dispatch_context;

/* B0 后第 48 位起为输出精度，第 51 位起为 Main10 编码精度。 */
static int packet_depth(const unsigned char *data, int size)
{
    int result = 0;
    for (int i = 0; i <= size - 11; ++i) {
        if (data[i] || data[i + 1] || data[i + 2] != 1 || data[i + 3] != 0xb0)
            continue;
        int profile = data[i + 4];
        if (profile != DAVS2_PROFILE_MAIN && profile != DAVS2_PROFILE_MAIN_PIC &&
            profile != DAVS2_PROFILE_MAIN10)
            return -1;
        int output = (data[i + 10] >> 5) & 7;
        int coding = profile == DAVS2_PROFILE_MAIN10 ? (data[i + 10] >> 2) & 7 : 1;
        if (output < 1 || output > 2 || coding < 1 || coding > 2 || output > coding)
            return -1;
        int depth = 6 + coding * 2;
        if (result && result != depth)
            return -1;
        result = depth;
    }
    return result;
}

static int fail(dispatch_context *ctx)
{
    if (!ctx->failed)
        fprintf(stderr, "[davs2] 不支持的位深、位深切换或无效序列头\n");
    ctx->failed = 1;
    return DAVS2_ERROR;
}

void *davs2_decoder_open(davs2_param_t *param)
{
    if (!param)
        return NULL;
    dispatch_context *ctx = calloc(1, sizeof(*ctx));
    if (ctx)
        ctx->param = *param;
    return ctx;
}

int davs2_decoder_send_packet(void *decoder, davs2_packet_t *packet)
{
    dispatch_context *ctx = decoder;
    if (!ctx || !packet || packet->len < 0 || (packet->len && !packet->data))
        return DAVS2_ERROR;
    if (ctx->failed)
        return DAVS2_ERROR;
    if (!packet->len)
        return DAVS2_DEFAULT;
    int depth = packet_depth(packet->data, packet->len);
    if (depth < 0 || (ctx->api && depth && depth != ctx->depth))
        return fail(ctx);
    if (ctx->api)
        return ctx->api->send(ctx->decoder, packet);

    /* 支持序列头跨包；限制尚未识别的输入，避免无头数据无限占用内存。 */
    if (packet->len > 64 * 1024 * 1024 - ctx->pending_size)
        return fail(ctx);
    unsigned char *buffer = realloc(ctx->pending, ctx->pending_size + packet->len);
    if (!buffer)
        return fail(ctx);
    ctx->pending = buffer;
    if (!ctx->pending_size) {
        ctx->pts = packet->pts;
        ctx->dts = packet->dts;
    }
    memcpy(buffer + ctx->pending_size, packet->data, packet->len);
    ctx->pending_size += packet->len;
    depth = packet_depth(buffer, ctx->pending_size);
    if (depth < 0)
        return fail(ctx);
    if (!depth)
        return DAVS2_DEFAULT;
    ctx->depth = depth;
    ctx->api = depth == 10 ? &api10 : &api8;
    ctx->decoder = ctx->api->open(&ctx->param);
    if (!ctx->decoder) {
        ctx->api = NULL;
        return fail(ctx);
    }
    davs2_packet_t combined = {buffer, ctx->pending_size, ctx->pts, ctx->dts};
    int result = ctx->api->send(ctx->decoder, &combined);
    free(ctx->pending);
    ctx->pending = NULL;
    ctx->pending_size = 0;
    return result;
}

int davs2_decoder_recv_frame(void *decoder, davs2_seq_info_t *header, davs2_picture_t *frame)
{
    dispatch_context *ctx = decoder;
    if (!ctx || ctx->failed)
        return DAVS2_ERROR;
    return ctx->api ? ctx->api->recv(ctx->decoder, header, frame) : DAVS2_DEFAULT;
}

int davs2_decoder_flush(void *decoder, davs2_seq_info_t *header, davs2_picture_t *frame)
{
    dispatch_context *ctx = decoder;
    if (!ctx || ctx->failed)
        return DAVS2_ERROR;
    return ctx->api ? ctx->api->flush(ctx->decoder, header, frame) : DAVS2_END;
}

void davs2_decoder_frame_unref(void *decoder, davs2_picture_t *frame)
{
    dispatch_context *ctx = decoder;
    if (ctx && ctx->api)
        ctx->api->unref(ctx->decoder, frame);
}

void davs2_decoder_close(void *decoder)
{
    dispatch_context *ctx = decoder;
    if (!ctx)
        return;
    if (ctx->api)
        ctx->api->close(ctx->decoder);
    free(ctx->pending);
    free(ctx);
}
