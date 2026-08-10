/*
 * Patch for pocketbook/main.c in branch bigfix_download.
 *
 * Integration:
 * 1. Copy DOWNLOAD_* defines near the existing #define block.
 * 2. Copy DownloadTransportResult and helper functions before
 *    download_book_to_device().
 * 3. Replace the current download_book_to_device() with the version below.
 *
 * The current text/profile/search requests may continue using QuickDownload().
 * Only EPUB transport switches to DownloadTo() + session polling.
 */

#define BOOKS_DIR "/mnt/ext1/Books"
#define DOWNLOAD_ATTEMPTS 2
#define DOWNLOAD_SESSION_TIMEOUT 45
#define DOWNLOAD_TOTAL_TIMEOUT 60
#define DOWNLOAD_POLL_US 250000
#define DOWNLOAD_REPORT_TIMEOUT 5


typedef struct {
    int http_status;
    int net_status;
    long bytes;
    char error[64];
} DownloadTransportResult;


static bool file_is_epub(const char *path, long *size_out) {
    FILE *file;
    unsigned char signature[2];
    long size;

    if (size_out) *size_out = 0;
    if (!path || !path[0]) return false;

    file = fopen(path, "rb");
    if (!file) return false;

    if (fread(signature, 1, sizeof(signature), file) != sizeof(signature)) {
        fclose(file);
        return false;
    }

    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return false;
    }

    size = ftell(file);
    fclose(file);

    if (size_out && size > 0) *size_out = size;

    return (
        size > 2 &&
        signature[0] == 'P' &&
        signature[1] == 'K'
    );
}


static void set_transport_error(
    DownloadTransportResult *result,
    const char *error
) {
    if (!result) return;
    safe_copy(
        result->error,
        error ? error : "unknown",
        sizeof(result->error)
    );
}


static bool download_to_temp_file(
    const char *url,
    const char *tmp_path,
    DownloadTransportResult *result
) {
    int session;
    int start_result;
    int status = NET_OK;
    time_t started;
    bool seen_activity = false;
    bool completed = false;

    if (!url || !url[0] || !tmp_path || !tmp_path[0] || !result) {
        return false;
    }

    memset(result, 0, sizeof(*result));
    result->net_status = NET_OK;
    safe_copy(result->error, "unknown", sizeof(result->error));

    remove(tmp_path);

    session = NewSession();
    if (session < 0) {
        set_transport_error(result, "new_session_failed");
        return false;
    }

    start_result = DownloadTo(
        session,
        url,
        0,
        tmp_path,
        DOWNLOAD_SESSION_TIMEOUT
    );

    if (start_result != 0) {
        set_transport_error(result, "download_start_failed");
        return false;
    }

    started = time(NULL);

    while ((time(NULL) - started) < DOWNLOAD_TOTAL_TIMEOUT) {
        iv_sessioninfo *info;

        status = GetSessionStatus(session);
        result->net_status = status;
        info = GetSessionInfo(session);

        if (status == NET_CONNECT || status == NET_TRANSFER) {
            seen_activity = true;
        }

        if (info) {
            result->http_status = info->response;
            if (info->progress >= 0) {
                result->bytes = info->progress;
            }
            if (info->response > 0 || info->progress > 0) {
                seen_activity = true;
            }
        }

        if (
            status != NET_OK &&
            status != NET_CONNECT &&
            status != NET_TRANSFER
        ) {
            char error[64];
            snprintf(error, sizeof(error), "network_%d", status);
            set_transport_error(result, error);
            break;
        }

        /*
         * InkView returns the session to NET_OK when the async transfer
         * finishes. Do not treat the initial NET_OK as completion: first
         * wait until the request has actually become active.
         */
        if (seen_activity && status == NET_OK && info && info->response > 0) {
            if (info->response >= 200 && info->response < 300) {
                completed = true;
            } else {
                char error[64];
                snprintf(error, sizeof(error), "http_%d", info->response);
                set_transport_error(result, error);
            }
            break;
        }

        usleep(DOWNLOAD_POLL_US);
    }

    if (!completed && strcmp(result->error, "unknown") == 0) {
        set_transport_error(result, "transport_timeout");
    }

    if (completed) {
        long file_size = 0;

        if (!file_is_epub(tmp_path, &file_size)) {
            result->bytes = file_size;
            set_transport_error(result, "invalid_epub");
            completed = false;
        } else {
            result->bytes = file_size;
            result->error[0] = '\0';
        }
    }

    if (!completed) {
        remove(tmp_path);
    }

    return completed;
}


static void report_download_client_result(
    const BookEntry *book,
    const char *status,
    long bytes,
    int attempts,
    long duration_ms,
    int http_status,
    int net_status,
    const char *error
) {
    char encoded_title[1024];
    char encoded_error[512];
    char report_url[URL_LEN];
    char *response;

    if (!user_uid[0] || !status || !status[0]) return;

    url_encode(
        book && book->title[0] ? book->title : "-",
        encoded_title,
        sizeof(encoded_title)
    );
    url_encode(
        error && error[0] ? error : "-",
        encoded_error,
        sizeof(encoded_error)
    );

    snprintf(
        report_url,
        sizeof(report_url),
        "%s/download/client-result"
        "?uid=%s"
        "&status=%s"
        "&bytes=%ld"
        "&attempts=%d"
        "&duration_ms=%ld"
        "&http_status=%d"
        "&net_status=%d"
        "&title=%s"
        "&error=%s",
        server_url,
        user_uid,
        status,
        bytes,
        attempts,
        duration_ms,
        http_status,
        net_status,
        encoded_title,
        encoded_error
    );

    /* Telemetry failure must not change the result of the book download. */
    response = http_get_text(report_url, DOWNLOAD_REPORT_TIMEOUT);
    if (response) free(response);
}


static void download_book_to_device(BookEntry *book) {
    char encoded_url[6144];
    char url[URL_LEN];
    char filename[256];
    char filepath[512];
    char tmp_path[560];
    char stale_tmp[560];
    DownloadTransportResult transport;
    int attempt;
    int i;
    bool success = false;
    time_t started;

    if (!book || !book->url[0] || !user_uid[0]) return;

    url_encode(book->url, encoded_url, sizeof(encoded_url));

    snprintf(
        url,
        sizeof(url),
        "%s/download?uid=%s&url=%s",
        server_url,
        user_uid,
        encoded_url
    );

    system("mkdir -p " BOOKS_DIR);

    snprintf(
        filename,
        sizeof(filename),
        "%s - %s",
        book->author,
        book->title
    );
    sanitize_filename(filename);
    truncate_utf8(filename, 220);
    strncat(
        filename,
        ".epub",
        sizeof(filename) - strlen(filename) - 1
    );

    snprintf(filepath, sizeof(filepath), BOOKS_DIR "/%s", filename);

    memset(&transport, 0, sizeof(transport));
    started = time(NULL);

    for (attempt = 1; attempt <= DOWNLOAD_ATTEMPTS; attempt++) {
        snprintf(tmp_path, sizeof(tmp_path), "%s.part%d", filepath, attempt);

        show_progress(
            attempt == 1
                ? "Скачивание EPUB..."
                : "Повтор загрузки..."
        );

        if (download_to_temp_file(url, tmp_path, &transport)) {
            if (rename(tmp_path, filepath) == 0) {
                success = true;
                break;
            }

            set_transport_error(&transport, "rename_failed");
            remove(tmp_path);
        }

        /* Permanent client errors are not retried. */
        if (
            transport.http_status >= 400 &&
            transport.http_status < 500
        ) {
            break;
        }
    }

    for (i = 1; i <= DOWNLOAD_ATTEMPTS; i++) {
        snprintf(stale_tmp, sizeof(stale_tmp), "%s.part%d", filepath, i);
        remove(stale_tmp);
    }

    if (success) {
        report_download_client_result(
            book,
            "success",
            transport.bytes,
            attempt,
            (long)(time(NULL) - started) * 1000L,
            transport.http_status,
            transport.net_status,
            NULL
        );

        Message(
            ICON_INFORMATION,
            "BookFerry",
            "EPUB скачан в папку Books",
            2200
        );
        return;
    }

    report_download_client_result(
        book,
        "error",
        transport.bytes,
        attempt > DOWNLOAD_ATTEMPTS ? DOWNLOAD_ATTEMPTS : attempt,
        (long)(time(NULL) - started) * 1000L,
        transport.http_status,
        transport.net_status,
        transport.error
    );

    Message(
        ICON_ERROR,
        "BookFerry",
        "Не удалось скачать EPUB",
        3000
    );
}
