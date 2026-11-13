#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <inkview.h>

#define DEFAULT_SERVER_URL "https://api.heartlab.app"

#define CONFIG_DIR  "/mnt/ext1/system/config/BookFerry"
#define CONFIG_FILE "/mnt/ext1/system/config/BookFerry/config.cfg"

#define MAX_ENTRIES 160
#define MAX_CATALOGS 20
#define ITEMS_PER_PAGE 5
#define URL_LEN 8192

#define BOOKS_DIR "/mnt/ext1/Books"
#define DOWNLOAD_ATTEMPTS 2
#define DOWNLOAD_SESSION_TIMEOUT 45
#define DOWNLOAD_TOTAL_TIMEOUT_MS 60000LL
#define DOWNLOAD_POLL_MS 250
#define DOWNLOAD_REDRAW_MS 1000LL
#define DOWNLOAD_REPORT_TIMEOUT 5
#define DOWNLOAD_REPORT_POLL_MS 250
#define DOWNLOAD_REPORT_FILE "/tmp/bookferry_client_result.tmp"

enum {
    MODE_HOME = 0,
    MODE_RESULTS,
    MODE_ABOUT,
    MODE_CATALOGS,
    MODE_DOWNLOAD
};

typedef struct {
    char title[256];
    char author[256];
    char url[2048];
} BookEntry;

typedef struct {
    int id;
    bool custom;
    char name[256];
} CatalogEntry;

typedef struct {
    int http_status;
    int net_status;
    long bytes;
    char error[64];
} DownloadTransportResult;

typedef struct {
    bool active;
    int return_mode;
    int session;
    int attempt;
    long long started_ms;
    long long attempt_started_ms;
    long long last_draw_ms;
    int percent;
    int last_draw_percent_bucket;
    long total_bytes;
    char status[128];
    char request_url[URL_LEN];
    char filepath[512];
    char tmp_path[560];
    BookEntry book;
    DownloadTransportResult transport;
} DownloadState;

ifont *font;
irect main_rect;

char user_uid[64] = "";
char catalog_name[256] = "Не выбрана";
char custom_opds_url[1024] = "";
char server_url[512] = DEFAULT_SERVER_URL;
char search_text[256] = "";
char next_page_url[2048] = "";

BookEntry entries[MAX_ENTRIES];
CatalogEntry catalogs[MAX_CATALOGS];

int app_mode = MODE_HOME;
int entries_count = 0;
int current_page = 0;
int catalogs_count = 0;
int catalog_page = 0;
time_t last_tap_time = 0;
bool startup_synced = false;

static DownloadState download_state;
static int report_session = -1;
static long long report_started_ms = 0;

static void draw_screen(void);
static void download_poll_timer(void);
static void report_poll_timer(void);


static void safe_copy(char *dst, const char *src, int dst_len) {
    if (!dst || dst_len <= 0) return;
    if (!src) src = "";

    strncpy(dst, src, dst_len - 1);
    dst[dst_len - 1] = '\0';
}

static int hex_value(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

static void percent_decode(const char *src, char *dst, int dst_len) {
    int i = 0;
    int j = 0;

    if (!dst || dst_len <= 0) return;
    dst[0] = '\0';
    if (!src) return;

    while (src[i] && j < dst_len - 1) {
        if (src[i] == '%' && src[i + 1] && src[i + 2]) {
            int hi = hex_value(src[i + 1]);
            int lo = hex_value(src[i + 2]);

            if (hi >= 0 && lo >= 0) {
                dst[j++] = (char)((hi << 4) | lo);
                i += 3;
                continue;
            }
        }

        dst[j++] = src[i] == '+' ? ' ' : src[i];
        i++;
    }

    dst[j] = '\0';
}

static void url_encode(const char *src, char *dst, int dst_len) {
    static const char hex[] = "0123456789ABCDEF";
    int i = 0;
    int j = 0;

    if (!dst || dst_len <= 0) return;
    dst[0] = '\0';
    if (!src) return;

    while (src[i] && j < dst_len - 1) {
        unsigned char c = (unsigned char)src[i];
        bool safe =
            (c >= 'A' && c <= 'Z') ||
            (c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9') ||
            c == '-' || c == '_' || c == '.' || c == '~';

        if (safe) {
            dst[j++] = (char)c;
        } else {
            if (j + 3 >= dst_len) break;
            dst[j++] = '%';
            dst[j++] = hex[(c >> 4) & 0x0f];
            dst[j++] = hex[c & 0x0f];
        }
        i++;
    }

    dst[j] = '\0';
}

static int split_fields(char *line, char **fields, int max_fields) {
    int count = 0;
    char *p;

    if (!line || !fields || max_fields <= 0) return 0;

    fields[count++] = line;
    p = line;

    while (*p && count < max_fields) {
        if (*p == '\t') {
            *p = '\0';
            fields[count++] = p + 1;
        }
        p++;
    }

    return count;
}

static long long now_ms(void) {
    struct timeval tv;

    gettimeofday(&tv, NULL);
    return ((long long)tv.tv_sec * 1000LL) + (tv.tv_usec / 1000LL);
}

static long file_size(const char *path) {
    struct stat st;

    if (!path || !path[0]) return 0;
    if (stat(path, &st) != 0) return 0;
    if (!S_ISREG(st.st_mode) || st.st_size <= 0) return 0;

    return (long)st.st_size;
}

static char *http_get_text(const char *url, int timeout) {
    int size = 0;
    void *raw = QuickDownload(url, &size, timeout);
    char *text;

    if (!raw || size <= 0) {
        if (raw) free(raw);
        return NULL;
    }

    text = (char *)malloc(size + 1);
    if (!text) {
        free(raw);
        return NULL;
    }

    memcpy(text, raw, size);
    text[size] = '\0';
    free(raw);
    return text;
}

static void sanitize_filename(char *name) {
    int i;

    for (i = 0; name && name[i]; i++) {
        unsigned char c = (unsigned char)name[i];

        if (c < 32 || strchr("/\\:*?\"|<>", c)) {
            name[i] = '_';
        }
    }
}

static void truncate_utf8(char *text, int max_bytes) {
    int len;

    if (!text || max_bytes <= 0) return;

    len = (int)strlen(text);
    if (len <= max_bytes) return;

    text[max_bytes] = '\0';

    while (
        max_bytes > 0 &&
        (((unsigned char)text[max_bytes - 1] & 0xc0) == 0x80)
    ) {
        text[--max_bytes] = '\0';
    }
}

static void clear_entries(void) {
    entries_count = 0;
    current_page = 0;
    next_page_url[0] = '\0';
    memset(entries, 0, sizeof(entries));
}

static void save_settings(void) {
    FILE *file;

    system("mkdir -p " CONFIG_DIR);

    file = fopen(CONFIG_FILE, "w");
    if (!file) return;

    fprintf(file, "%s\n", user_uid);
    fprintf(file, "%s\n", catalog_name);
    fprintf(file, "%s\n", custom_opds_url);
    fprintf(file, "%s\n", server_url);
    fclose(file);
}

static void load_settings(void) {
    FILE *file = fopen(CONFIG_FILE, "r");

    if (!file) return;

    if (fgets(user_uid, sizeof(user_uid), file)) {
        user_uid[strcspn(user_uid, "\r\n")] = '\0';
    }

    if (fgets(catalog_name, sizeof(catalog_name), file)) {
        catalog_name[strcspn(catalog_name, "\r\n")] = '\0';
    }

    if (fgets(custom_opds_url, sizeof(custom_opds_url), file)) {
        custom_opds_url[strcspn(custom_opds_url, "\r\n")] = '\0';
    }

    if (fgets(server_url, sizeof(server_url), file)) {
        server_url[strcspn(server_url, "\r\n")] = '\0';
        if (!server_url[0]) {
            safe_copy(server_url, DEFAULT_SERVER_URL, sizeof(server_url));
        }
    }

    fclose(file);
}

static void show_progress(const char *message) {
    int w = main_rect.w * 70 / 100;
    int h = main_rect.h * 15 / 100;
    int x = main_rect.x + (main_rect.w - w) / 2;
    int y = main_rect.y + (main_rect.h - h) / 2;

    FillArea(x, y, w, h, WHITE);
    DrawRect(x, y, w, h, BLACK);
    DrawString(
        x + (w - StringWidth(message)) / 2,
        y + (h - font->height) / 2,
        message
    );
    FullUpdate();
}

static bool register_user(void) {
    char url[URL_LEN];
    char *text;
    char *fields[5];
    int count;

    snprintf(
        url,
        sizeof(url),
        "%s/users/register?client_type=pocketbook&plain=1&ts=%ld",
        server_url,
        (long)time(NULL)
    );

    show_progress("Регистрация...");
    text = http_get_text(url, 30);
    if (!text) return false;

    text[strcspn(text, "\r\n")] = '\0';
    count = split_fields(text, fields, 5);

    if (count < 4 || strcmp(fields[0], "UID") != 0) {
        free(text);
        return false;
    }

    safe_copy(user_uid, fields[1], sizeof(user_uid));
    percent_decode(fields[3], catalog_name, sizeof(catalog_name));
    custom_opds_url[0] = '\0';
    save_settings();

    free(text);
    return true;
}

static bool load_profile(void) {
    char url[URL_LEN];
    char *text;
    char *fields[6];
    int count;

    if (!user_uid[0]) return false;

    snprintf(
        url,
        sizeof(url),
        "%s/users/%s?plain=1",
        server_url,
        user_uid
    );

    text = http_get_text(url, 20);
    if (!text) return false;

    text[strcspn(text, "\r\n")] = '\0';
    count = split_fields(text, fields, 6);

    if (count < 5 || strcmp(fields[0], "PROFILE") != 0) {
        free(text);
        return false;
    }

    percent_decode(fields[2], catalog_name, sizeof(catalog_name));

    if (strcmp(fields[3], "custom") == 0) {
        percent_decode(
            fields[4],
            custom_opds_url,
            sizeof(custom_opds_url)
        );
    } else {
        custom_opds_url[0] = '\0';
    }

    save_settings();
    free(text);
    return true;
}

static bool ensure_user(void) {
    if (user_uid[0]) return true;

    if (!register_user()) {
        Message(
            ICON_ERROR,
            "BookFerry",
            "Не удалось зарегистрировать устройство",
            3000
        );
        return false;
    }

    return true;
}

static bool load_catalogs(void) {
    char url[URL_LEN];
    char *text;
    char *line;

    snprintf(url, sizeof(url), "%s/catalogs?plain=1", server_url);

    show_progress("Библиотеки...");
    text = http_get_text(url, 30);
    if (!text) return false;

    catalogs_count = 0;
    catalog_page = 0;
    memset(catalogs, 0, sizeof(catalogs));

    line = text;

    while (line && *line && catalogs_count < MAX_CATALOGS) {
        char *eol = strchr(line, '\n');
        char *fields[4];
        int count;

        if (eol) *eol = '\0';
        line[strcspn(line, "\r")] = '\0';
        count = split_fields(line, fields, 4);

        if (count >= 3 && strcmp(fields[0], "CATALOG") == 0) {
            CatalogEntry *catalog = &catalogs[catalogs_count++];

            catalog->id = atoi(fields[1]);
            percent_decode(
                fields[2],
                catalog->name,
                sizeof(catalog->name)
            );
        } else if (
            count >= 2 &&
            strcmp(fields[0], "CUSTOM") == 0
        ) {
            CatalogEntry *catalog = &catalogs[catalogs_count++];

            catalog->custom = true;
            percent_decode(
                fields[1],
                catalog->name,
                sizeof(catalog->name)
            );
        }

        line = eol ? eol + 1 : NULL;
    }

    free(text);
    return catalogs_count > 0;
}

static bool select_catalog(CatalogEntry *catalog) {
    char url[URL_LEN];
    char *text;
    char *fields[4];
    int count;

    if (!catalog || catalog->custom || !user_uid[0]) return false;

    snprintf(
        url,
        sizeof(url),
        "%s/users/%s/catalog?catalog_id=%d&plain=1",
        server_url,
        user_uid,
        catalog->id
    );

    show_progress("Сохраняю...");
    text = http_get_text(url, 30);
    if (!text) return false;

    text[strcspn(text, "\r\n")] = '\0';
    count = split_fields(text, fields, 4);

    if (count < 3 || strcmp(fields[0], "OK") != 0) {
        free(text);
        return false;
    }

    percent_decode(fields[2], catalog_name, sizeof(catalog_name));
    custom_opds_url[0] = '\0';
    clear_entries();
    save_settings();

    free(text);
    return true;
}

static bool select_custom_opds(const char *opds_url) {
    char encoded[3072];
    char url[URL_LEN];
    char *text;
    char *fields[4];
    int count;

    if (!opds_url || !opds_url[0] || !user_uid[0]) return false;

    url_encode(opds_url, encoded, sizeof(encoded));

    snprintf(
        url,
        sizeof(url),
        "%s/users/%s/opds?opds_url=%s&plain=1",
        server_url,
        user_uid,
        encoded
    );

    show_progress("Проверяю OPDS...");
    text = http_get_text(url, 60);
    if (!text) return false;

    text[strcspn(text, "\r\n")] = '\0';
    count = split_fields(text, fields, 4);

    if (count < 3 || strcmp(fields[0], "OK") != 0) {
        free(text);
        return false;
    }

    percent_decode(fields[2], catalog_name, sizeof(catalog_name));

    if (atoi(fields[1]) == 0) {
        safe_copy(custom_opds_url, opds_url, sizeof(custom_opds_url));
    } else {
        custom_opds_url[0] = '\0';
    }

    clear_entries();
    save_settings();

    free(text);
    return true;
}

static bool parse_search_page(char *text) {
    char *line = text;
    bool got_books = false;

    next_page_url[0] = '\0';

    while (line && *line) {
        char *eol = strchr(line, '\n');
        char *fields[5];
        int count;

        if (eol) *eol = '\0';
        line[strcspn(line, "\r")] = '\0';
        count = split_fields(line, fields, 5);

        if (
            count >= 4 &&
            strcmp(fields[0], "BOOK") == 0 &&
            entries_count < MAX_ENTRIES
        ) {
            BookEntry *book = &entries[entries_count];

            memset(book, 0, sizeof(BookEntry));
            percent_decode(fields[1], book->title, sizeof(book->title));
            percent_decode(fields[2], book->author, sizeof(book->author));
            percent_decode(fields[3], book->url, sizeof(book->url));

            if (book->title[0] && book->url[0]) {
                if (!book->author[0]) {
                    safe_copy(
                        book->author,
                        "Неизвестный автор",
                        sizeof(book->author)
                    );
                }
                entries_count++;
                got_books = true;
            }
        } else if (
            count >= 2 &&
            strcmp(fields[0], "NEXT") == 0
        ) {
            percent_decode(
                fields[1],
                next_page_url,
                sizeof(next_page_url)
            );
        }

        line = eol ? eol + 1 : NULL;
    }

    return got_books;
}

static bool load_search_page(const char *url, const char *message) {
    char *text;
    bool result;

    if (message) show_progress(message);

    text = http_get_text(url, 90);
    if (!text) return false;

    result = parse_search_page(text);
    free(text);
    return result;
}

static void do_search(void) {
    char query[1024];
    char url[URL_LEN];

    if (!search_text[0] || !ensure_user()) return;

    clear_entries();
    url_encode(search_text, query, sizeof(query));

    snprintf(
        url,
        sizeof(url),
        "%s/search?uid=%s&query=%s&plain=1",
        server_url,
        user_uid,
        query
    );

    if (!load_search_page(url, "Поиск...")) {
        Message(
            ICON_ERROR,
            "BookFerry",
            "Ничего не найдено или сервер недоступен",
            3000
        );
        return;
    }

    app_mode = MODE_RESULTS;
    current_page = 0;
}

static bool load_next_page(void) {
    char query[1024];
    char page[6144];
    char url[URL_LEN];
    int old_count = entries_count;

    if (!next_page_url[0]) return false;

    url_encode(search_text, query, sizeof(query));
    url_encode(next_page_url, page, sizeof(page));

    snprintf(
        url,
        sizeof(url),
        "%s/search?uid=%s&query=%s&page_url=%s&plain=1",
        server_url,
        user_uid,
        query,
        page
    );

    if (!load_search_page(url, "Следующая страница...")) return false;
    return entries_count > old_count;
}

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

    fclose(file);
    size = file_size(path);

    if (size_out) *size_out = size;

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

static void close_report_session(bool abort_first) {
    if (report_session < 0) return;

    if (abort_first) {
        AbortTransfer(report_session);
    }

    CloseSession(report_session);
    report_session = -1;
    report_started_ms = 0;
    remove(DOWNLOAD_REPORT_FILE);
}

static void report_poll_timer(void) {
    int status;
    iv_sessioninfo *info;
    long long elapsed;

    if (report_session < 0) return;

    status = GetSessionStatus(report_session);
    info = GetSessionInfo(report_session);
    elapsed = now_ms() - report_started_ms;

    if (status < 0) {
        close_report_session(false);
        return;
    }

    if (
        status == NET_OK &&
        info &&
        info->response != 0
    ) {
        close_report_session(false);
        return;
    }

    if (elapsed >= 7000LL) {
        close_report_session(true);
        return;
    }

    SetWeakTimer(
        "bookferry_report",
        report_poll_timer,
        DOWNLOAD_REPORT_POLL_MS
    );
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
    int session;
    int start_result;

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

    if (report_session >= 0) {
        ClearTimer(report_poll_timer);
        close_report_session(true);
    }

    remove(DOWNLOAD_REPORT_FILE);
    session = NewSession();
    if (session < 0) return;

    start_result = DownloadTo(
        session,
        report_url,
        NULL,
        DOWNLOAD_REPORT_FILE,
        DOWNLOAD_REPORT_TIMEOUT
    );

    if (start_result != NET_OK) {
        CloseSession(session);
        remove(DOWNLOAD_REPORT_FILE);
        return;
    }

    report_session = session;
    report_started_ms = now_ms();
    SetWeakTimer(
        "bookferry_report",
        report_poll_timer,
        DOWNLOAD_REPORT_POLL_MS
    );
}

static void close_download_session(bool abort_first) {
    if (download_state.session < 0) return;

    if (abort_first) {
        AbortTransfer(download_state.session);
    }

    CloseSession(download_state.session);
    download_state.session = -1;
}

static void cleanup_download_parts(void) {
    int i;
    char path[560];

    for (i = 1; i <= DOWNLOAD_ATTEMPTS; i++) {
        snprintf(
            path,
            sizeof(path),
            "%s.part%d",
            download_state.filepath,
            i
        );
        remove(path);
    }
}

static void prepare_download_tmp_path(void) {
    snprintf(
        download_state.tmp_path,
        sizeof(download_state.tmp_path),
        "%s.part%d",
        download_state.filepath,
        download_state.attempt
    );
}

static bool start_download_attempt(void) {
    iv_sessioninfo *info;
    int start_result;

    prepare_download_tmp_path();
    remove(download_state.tmp_path);

    memset(&download_state.transport, 0, sizeof(download_state.transport));
    download_state.transport.net_status = NET_OK;
    safe_copy(
        download_state.transport.error,
        "unknown",
        sizeof(download_state.transport.error)
    );

    download_state.total_bytes = 0;
    download_state.percent = -1;
    download_state.last_draw_percent_bucket = -1;
    download_state.attempt_started_ms = now_ms();

    download_state.session = NewSession();
    if (download_state.session < 0) {
        set_transport_error(
            &download_state.transport,
            "new_session_failed"
        );
        return false;
    }

    info = GetSessionInfo(download_state.session);
    if (info) {
        info->response = 0;
    }

    start_result = DownloadTo(
        download_state.session,
        download_state.request_url,
        NULL,
        download_state.tmp_path,
        DOWNLOAD_SESSION_TIMEOUT
    );

    if (start_result != NET_OK) {
        char error[64];

        download_state.transport.net_status = start_result;
        snprintf(
            error,
            sizeof(error),
            "download_start_%d",
            start_result
        );
        set_transport_error(&download_state.transport, error);
        close_download_session(false);
        remove(download_state.tmp_path);
        return false;
    }

    safe_copy(
        download_state.status,
        download_state.attempt == 1
            ? "Подключение к серверу..."
            : "Повторная попытка...",
        sizeof(download_state.status)
    );

    return true;
}

static bool download_should_retry(void) {
    if (download_state.attempt >= DOWNLOAD_ATTEMPTS) return false;

    if (
        download_state.transport.http_status >= 400 &&
        download_state.transport.http_status < 500
    ) {
        return false;
    }

    if (
        strcmp(download_state.transport.error, "cancelled_by_user") == 0
    ) {
        return false;
    }

    return true;
}

static void finish_download(bool success, const char *user_message) {
    long duration_ms;
    int attempts;
    BookEntry book_copy;
    DownloadTransportResult transport_copy;
    int return_mode;

    ClearTimer(download_poll_timer);
    close_download_session(false);

    duration_ms = (long)(now_ms() - download_state.started_ms);
    attempts = download_state.attempt;
    book_copy = download_state.book;
    transport_copy = download_state.transport;
    return_mode = download_state.return_mode;

    cleanup_download_parts();

    download_state.active = false;
    download_state.session = -1;
    app_mode = return_mode;
    draw_screen();

    if (success) {
        Message(
            ICON_INFORMATION,
            "BookFerry",
            user_message ? user_message : "EPUB скачан в папку Books",
            2200
        );

        report_download_client_result(
            &book_copy,
            "success",
            transport_copy.bytes,
            attempts,
            duration_ms,
            transport_copy.http_status,
            transport_copy.net_status,
            NULL
        );
    } else {
        Message(
            strcmp(transport_copy.error, "cancelled_by_user") == 0
                ? ICON_INFORMATION
                : ICON_ERROR,
            "BookFerry",
            user_message ? user_message : "Не удалось скачать EPUB",
            3000
        );

        report_download_client_result(
            &book_copy,
            "error",
            transport_copy.bytes,
            attempts,
            duration_ms,
            transport_copy.http_status,
            transport_copy.net_status,
            transport_copy.error
        );
    }
}

static void retry_or_finish_download(void) {
    close_download_session(false);
    remove(download_state.tmp_path);

    if (download_should_retry()) {
        download_state.attempt++;

        safe_copy(
            download_state.status,
            "Повторная попытка...",
            sizeof(download_state.status)
        );
        draw_screen();

        if (start_download_attempt()) {
            SetWeakTimer(
                "bookferry_download",
                download_poll_timer,
                DOWNLOAD_POLL_MS
            );
            return;
        }

        retry_or_finish_download();
        return;
    }

    finish_download(false, NULL);
}

static void download_poll_timer(void) {
    int status;
    iv_sessioninfo *info;
    long bytes;
    long long now;
    bool redraw = false;
    int percent_bucket = -1;

    if (!download_state.active || download_state.session < 0) return;

    now = now_ms();
    status = GetSessionStatus(download_state.session);
    info = GetSessionInfo(download_state.session);
    bytes = file_size(download_state.tmp_path);

    download_state.transport.net_status = status;
    download_state.transport.bytes = bytes;

    if (info) {
        download_state.transport.http_status = (int)info->response;

        if (info->length > 0) {
            download_state.total_bytes = (long)info->length;
        }
    }

    if (download_state.total_bytes > 0) {
        long long raw_percent =
            ((long long)bytes * 100LL) /
            (long long)download_state.total_bytes;

        if (raw_percent < 0) raw_percent = 0;
        if (raw_percent > 100) raw_percent = 100;
        download_state.percent = (int)raw_percent;
        percent_bucket = download_state.percent / 5;
    } else {
        download_state.percent = -1;
    }

    if (status < 0) {
        char error[64];

        snprintf(error, sizeof(error), "network_%d", status);
        set_transport_error(&download_state.transport, error);
        retry_or_finish_download();
        return;
    }

    if (
        info &&
        info->response >= 400
    ) {
        char error[64];

        snprintf(
            error,
            sizeof(error),
            "http_%ld",
            info->response
        );
        set_transport_error(&download_state.transport, error);
        retry_or_finish_download();
        return;
    }

    if (
        status == NET_OK &&
        info &&
        info->response != 0
    ) {
        if (info->response >= 200 && info->response < 300) {
            long final_size = 0;

            close_download_session(false);

            if (!file_is_epub(download_state.tmp_path, &final_size)) {
                download_state.transport.bytes = final_size;
                set_transport_error(
                    &download_state.transport,
                    "invalid_epub"
                );
                retry_or_finish_download();
                return;
            }

            download_state.transport.bytes = final_size;
            download_state.transport.net_status = NET_OK;
            download_state.transport.error[0] = '\0';

            if (
                rename(
                    download_state.tmp_path,
                    download_state.filepath
                ) != 0
            ) {
                set_transport_error(
                    &download_state.transport,
                    "rename_failed"
                );
                remove(download_state.tmp_path);
                retry_or_finish_download();
                return;
            }

            // Notify InkView after the validated EPUB has its final path.
            // Firmware determines whether this indexes the new book.
            BookReady(download_state.filepath);
            finish_download(true, "EPUB скачан в папку Books");
            return;
        }

        {
            char error[64];

            snprintf(
                error,
                sizeof(error),
                "http_%ld",
                info->response
            );
            set_transport_error(&download_state.transport, error);
            retry_or_finish_download();
            return;
        }
    }

    if (
        now - download_state.attempt_started_ms >=
        DOWNLOAD_TOTAL_TIMEOUT_MS
    ) {
        set_transport_error(
            &download_state.transport,
            "transport_timeout"
        );
        download_state.transport.net_status = NET_ETIMEOUT;
        close_download_session(true);
        retry_or_finish_download();
        return;
    }

    if (status == NET_CONNECT) {
        safe_copy(
            download_state.status,
            "Подключение к серверу...",
            sizeof(download_state.status)
        );
    } else if (status == NET_TRANSFER) {
        if (download_state.percent >= 0) {
            snprintf(
                download_state.status,
                sizeof(download_state.status),
                "Скачивание: %d%%",
                download_state.percent
            );
        } else if (bytes > 0) {
            snprintf(
                download_state.status,
                sizeof(download_state.status),
                "Скачивание: %ld КБ",
                bytes / 1024L
            );
        } else {
            safe_copy(
                download_state.status,
                "Получение EPUB...",
                sizeof(download_state.status)
            );
        }
    } else if (info && info->response >= 200 && info->response < 300) {
        safe_copy(
            download_state.status,
            "Завершение загрузки...",
            sizeof(download_state.status)
        );
    } else {
        safe_copy(
            download_state.status,
            "Ожидание ответа...",
            sizeof(download_state.status)
        );
    }

    if (
        now - download_state.last_draw_ms >= DOWNLOAD_REDRAW_MS
    ) {
        redraw = true;
    }

    if (
        percent_bucket >= 0 &&
        percent_bucket != download_state.last_draw_percent_bucket
    ) {
        redraw = true;
    }

    if (redraw) {
        download_state.last_draw_ms = now;
        download_state.last_draw_percent_bucket = percent_bucket;
        draw_screen();
    }

    SetWeakTimer(
        "bookferry_download",
        download_poll_timer,
        DOWNLOAD_POLL_MS
    );
}

static void start_download(BookEntry *book) {
    char encoded_url[6144];
    char filename[256];

    if (
        !book ||
        !book->url[0] ||
        !user_uid[0] ||
        download_state.active
    ) {
        return;
    }

    memset(&download_state, 0, sizeof(download_state));
    download_state.session = -1;
    download_state.active = true;
    download_state.return_mode = app_mode;
    download_state.attempt = 1;
    download_state.started_ms = now_ms();
    download_state.last_draw_ms = 0;
    download_state.percent = -1;
    download_state.last_draw_percent_bucket = -1;
    download_state.book = *book;

    url_encode(book->url, encoded_url, sizeof(encoded_url));

    snprintf(
        download_state.request_url,
        sizeof(download_state.request_url),
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

    snprintf(
        download_state.filepath,
        sizeof(download_state.filepath),
        BOOKS_DIR "/%s",
        filename
    );

    cleanup_download_parts();

    safe_copy(
        download_state.status,
        "Подготовка загрузки...",
        sizeof(download_state.status)
    );

    app_mode = MODE_DOWNLOAD;
    draw_screen();

    if (!start_download_attempt()) {
        retry_or_finish_download();
        return;
    }

    SetWeakTimer(
        "bookferry_download",
        download_poll_timer,
        DOWNLOAD_POLL_MS
    );
}

static void cancel_download(void) {
    if (!download_state.active) return;

    ClearTimer(download_poll_timer);

    download_state.transport.bytes = file_size(download_state.tmp_path);
    download_state.transport.net_status = NET_ABORTED;
    set_transport_error(
        &download_state.transport,
        "cancelled_by_user"
    );

    close_download_session(true);
    remove(download_state.tmp_path);
    finish_download(false, "Загрузка отменена");
}

static void draw_nav(
    int x,
    int width,
    int button_h,
    int spacing
) {
    int y = main_rect.y + main_rect.h - button_h;
    int w = (width - spacing * 2) / 3;

    DrawRect(x, y, w, button_h, BLACK);
    DrawString(
        x + (w - StringWidth("<")) / 2,
        y + (button_h - font->height) / 2,
        "<"
    );

    DrawRect(x + w + spacing, y, w, button_h, BLACK);
    DrawString(
        x + w + spacing + (w - StringWidth("Домой")) / 2,
        y + (button_h - font->height) / 2,
        "Домой"
    );

    DrawRect(x + (w + spacing) * 2, y, w, button_h, BLACK);
    DrawString(
        x + (w + spacing) * 2 + (w - StringWidth(">")) / 2,
        y + (button_h - font->height) / 2,
        ">"
    );
}

static void draw_download_screen(
    int x,
    int width,
    int button_h,
    int spacing
) {
    int y = main_rect.y + spacing;
    int bar_y;
    int bar_h = main_rect.h * 5 / 100;
    int cancel_y = main_rect.y + main_rect.h - button_h;
    char attempt_text[64];
    char bytes_text[96];
    char elapsed_text[96];
    long long elapsed_ms = now_ms() - download_state.started_ms;

    DrawString(x, y, "Скачивание EPUB");
    y += font->height * 2;

    DrawString(x, y, download_state.book.title);
    y += font->height + 10;
    DrawString(x, y, download_state.book.author);
    y += font->height * 2;

    DrawString(x, y, download_state.status);
    y += font->height + 16;

    snprintf(
        attempt_text,
        sizeof(attempt_text),
        "Попытка: %d/%d",
        download_state.attempt,
        DOWNLOAD_ATTEMPTS
    );
    DrawString(x, y, attempt_text);
    y += font->height + 10;

    if (download_state.transport.bytes > 0) {
        if (download_state.total_bytes > 0) {
            snprintf(
                bytes_text,
                sizeof(bytes_text),
                "%ld / %ld КБ",
                download_state.transport.bytes / 1024L,
                download_state.total_bytes / 1024L
            );
        } else {
            snprintf(
                bytes_text,
                sizeof(bytes_text),
                "Получено: %ld КБ",
                download_state.transport.bytes / 1024L
            );
        }
    } else {
        safe_copy(bytes_text, "Получено: 0 КБ", sizeof(bytes_text));
    }

    DrawString(x, y, bytes_text);
    y += font->height + 10;

    snprintf(
        elapsed_text,
        sizeof(elapsed_text),
        "Время: %lld сек",
        elapsed_ms / 1000LL
    );
    DrawString(x, y, elapsed_text);
    y += font->height + 16;

    bar_y = y;
    DrawRect(x, bar_y, width, bar_h, BLACK);

    if (download_state.percent > 0) {
        int fill_w =
            (width - 4) * download_state.percent / 100;

        if (fill_w > 0) {
            FillArea(
                x + 2,
                bar_y + 2,
                fill_w,
                bar_h - 4,
                BLACK
            );
        }
    }

    DrawRect(x, cancel_y, width, button_h, BLACK);
    DrawString(
        x + (width - StringWidth("Отмена")) / 2,
        cancel_y + (button_h - font->height) / 2,
        "Отмена"
    );
}

static void draw_screen(void) {
    int side = main_rect.w * 5 / 100;
    int x = main_rect.x + side;
    int width = main_rect.w - side * 2;
    int input_h = main_rect.h * 11 / 100;
    int button_h = main_rect.h * 9 / 100;
    int spacing = main_rect.h * 3 / 100;
    int y = main_rect.y + spacing;

    ClearScreen();
    SetFont(font, BLACK);

    if (app_mode == MODE_HOME) {
        int about_y = main_rect.y + main_rect.h - button_h - spacing;

        DrawRect(x, y, width, input_h, BLACK);
        DrawString(
            x + 20,
            y + input_h / 4 - font->height / 2,
            "Библиотека:"
        );
        DrawString(
            x + 20,
            y + input_h * 3 / 4 - font->height / 2,
            catalog_name
        );
        y += input_h + spacing;

        DrawRect(x, y, width, input_h, BLACK);
        DrawString(
            x + 20,
            y + input_h / 4 - font->height / 2,
            "Название или автор:"
        );
        DrawString(
            x + 20,
            y + input_h * 3 / 4 - font->height / 2,
            search_text
        );
        y += input_h + spacing;

        DrawRect(x, y, width, button_h, BLACK);
        DrawString(
            x + (width - StringWidth(">>> НАЧАТЬ ПОИСК <<<")) / 2,
            y + (button_h - font->height) / 2,
            ">>> НАЧАТЬ ПОИСК <<<"
        );

        DrawRect(x, about_y, width, button_h, BLACK);
        DrawString(
            x + (width - StringWidth("[ О программе ]")) / 2,
            about_y + (button_h - font->height) / 2,
            "[ О программе ]"
        );
    } else if (app_mode == MODE_RESULTS) {
        int zone_h = main_rect.h * 60 / 100;
        int item_h = zone_h / ITEMS_PER_PAGE;
        int start = current_page * ITEMS_PER_PAGE;
        int end = start + ITEMS_PER_PAGE;
        int total_pages;
        int i;
        char status[128];

        if (end > entries_count) end = entries_count;

        for (i = start; i < end; i++) {
            DrawString(
                x + 10,
                y + item_h / 4 - font->height / 2,
                entries[i].title
            );
            DrawString(
                x + 10,
                y + item_h * 3 / 4 - font->height / 2,
                entries[i].author
            );
            DrawLine(
                x,
                y + item_h - 2,
                x + width,
                y + item_h - 2,
                BLACK
            );
            y += item_h;
        }

        total_pages =
            (entries_count + ITEMS_PER_PAGE - 1) /
            ITEMS_PER_PAGE;
        if (total_pages < 1) total_pages = 1;

        snprintf(
            status,
            sizeof(status),
            next_page_url[0]
                ? "Найдено: %d+ | Стр. %d/%d"
                : "Найдено: %d | Стр. %d/%d",
            entries_count,
            current_page + 1,
            total_pages
        );

        DrawString(
            x,
            main_rect.y + main_rect.h -
                button_h - font->height - 25,
            status
        );
        draw_nav(x, width, button_h, spacing);
    } else if (app_mode == MODE_CATALOGS) {
        int zone_h = main_rect.h * 58 / 100;
        int item_h = zone_h / ITEMS_PER_PAGE;
        int start = catalog_page * ITEMS_PER_PAGE;
        int end = start + ITEMS_PER_PAGE;
        int i;

        if (end > catalogs_count) end = catalogs_count;

        for (i = start; i < end; i++) {
            DrawString(
                x + 10,
                y + (item_h - font->height) / 2,
                catalogs[i].name
            );
            DrawLine(
                x,
                y + item_h - 2,
                x + width,
                y + item_h - 2,
                BLACK
            );
            y += item_h;
        }

        draw_nav(x, width, button_h, spacing);
    } else if (app_mode == MODE_ABOUT) {
        int back_y = main_rect.y + main_rect.h - button_h;

        DrawString(x, y, "BookFerry для PocketBook");
        y += font->height * 2;
        DrawString(x, y, "Версия: 2.2");
        y += font->height + 10;
        DrawString(x, y, "Поиск через сервер BookFerry");
        y += font->height + 10;
        DrawString(x, y, "Асинхронная загрузка EPUB");
        y += font->height + 10;
        DrawString(x, y, "Кирилл Т");
        y += font->height + 10;
        DrawString(x, y, "kirillterentiev@gmail.com");

        DrawRect(x, back_y, width, button_h, BLACK);
        DrawString(
            x + (width - StringWidth("Назад")) / 2,
            back_y + (button_h - font->height) / 2,
            "Назад"
        );
    } else if (app_mode == MODE_DOWNLOAD) {
        draw_download_screen(x, width, button_h, spacing);
    }

    FullUpdate();
}

static void keyboard_search_handler(char *text) {
    if (text) {
        safe_copy(search_text, text, sizeof(search_text));
    }
    draw_screen();
}

static void keyboard_opds_handler(char *text) {
    if (!text || !text[0]) {
        draw_screen();
        return;
    }

    if (select_custom_opds(text)) {
        Message(
            ICON_INFORMATION,
            "BookFerry",
            "OPDS подключён",
            1800
        );
        app_mode = MODE_HOME;
    } else {
        Message(
            ICON_ERROR,
            "BookFerry",
            "Не удалось подключить OPDS",
            3000
        );
    }

    draw_screen();
}

static void handle_tap(int px, int py) {
    int side = main_rect.w * 5 / 100;
    int x = main_rect.x + side;
    int width = main_rect.w - side * 2;
    int input_h = main_rect.h * 11 / 100;
    int button_h = main_rect.h * 9 / 100;
    int spacing = main_rect.h * 3 / 100;

    if (app_mode == MODE_DOWNLOAD) {
        int cancel_y = main_rect.y + main_rect.h - button_h;

        if (
            px >= x && px <= x + width &&
            py >= cancel_y && py <= cancel_y + button_h
        ) {
            cancel_download();
        }
        return;
    }

    if (time(NULL) - last_tap_time < 1) return;
    last_tap_time = time(NULL);

    if (app_mode == MODE_HOME) {
        int y = main_rect.y + spacing;
        int about_y = main_rect.y + main_rect.h - button_h - spacing;

        if (
            px >= x && px <= x + width &&
            py >= y && py <= y + input_h
        ) {
            if (ensure_user() && load_catalogs()) {
                app_mode = MODE_CATALOGS;
            } else {
                Message(
                    ICON_ERROR,
                    "BookFerry",
                    "Не удалось получить библиотеки",
                    3000
                );
            }
            draw_screen();
            return;
        }

        y += input_h + spacing;

        if (
            px >= x && px <= x + width &&
            py >= y && py <= y + input_h
        ) {
            OpenKeyboard(
                "Поиск",
                search_text,
                255,
                16,
                keyboard_search_handler
            );
            return;
        }

        y += input_h + spacing;

        if (
            px >= x && px <= x + width &&
            py >= y && py <= y + button_h &&
            search_text[0]
        ) {
            do_search();
            draw_screen();
            return;
        }

        if (
            px >= x && px <= x + width &&
            py >= about_y && py <= about_y + button_h
        ) {
            app_mode = MODE_ABOUT;
            draw_screen();
            return;
        }
    }

    if (app_mode == MODE_RESULTS) {
        int nav_y = main_rect.y + main_rect.h - button_h;
        int nav_w = (width - spacing * 2) / 3;
        int list_y = main_rect.y + spacing;
        int zone_h = main_rect.h * 60 / 100;

        if (py >= nav_y && py <= nav_y + button_h) {
            if (px >= x && px <= x + nav_w) {
                if (current_page > 0) {
                    current_page--;
                } else {
                    app_mode = MODE_HOME;
                    clear_entries();
                }
            } else if (
                px >= x + nav_w + spacing &&
                px <= x + nav_w + spacing + nav_w
            ) {
                app_mode = MODE_HOME;
                clear_entries();
            } else if (
                px >= x + (nav_w + spacing) * 2 &&
                px <= x + width
            ) {
                int total =
                    (entries_count + ITEMS_PER_PAGE - 1) /
                    ITEMS_PER_PAGE;

                if (current_page < total - 1) {
                    current_page++;
                } else if (
                    next_page_url[0] &&
                    entries_count < MAX_ENTRIES
                ) {
                    if (load_next_page()) {
                        current_page++;
                    } else {
                        Message(
                            ICON_ERROR,
                            "BookFerry",
                            "Следующая страница не загрузилась",
                            3000
                        );
                    }
                }
            }

            draw_screen();
            return;
        }

        if (py >= list_y && py < list_y + zone_h) {
            int item_h = zone_h / ITEMS_PER_PAGE;
            int index =
                current_page * ITEMS_PER_PAGE +
                (py - list_y) / item_h;

            if (index >= 0 && index < entries_count) {
                start_download(&entries[index]);
            }
            return;
        }
    }

    if (app_mode == MODE_CATALOGS) {
        int nav_y = main_rect.y + main_rect.h - button_h;
        int nav_w = (width - spacing * 2) / 3;
        int list_y = main_rect.y + spacing;
        int zone_h = main_rect.h * 58 / 100;

        if (py >= nav_y && py <= nav_y + button_h) {
            if (px >= x && px <= x + nav_w) {
                if (catalog_page > 0) catalog_page--;
            } else if (
                px >= x + nav_w + spacing &&
                px <= x + nav_w + spacing + nav_w
            ) {
                app_mode = MODE_HOME;
            } else if (
                px >= x + (nav_w + spacing) * 2 &&
                px <= x + width
            ) {
                int total =
                    (catalogs_count + ITEMS_PER_PAGE - 1) /
                    ITEMS_PER_PAGE;

                if (catalog_page < total - 1) {
                    catalog_page++;
                }
            }

            draw_screen();
            return;
        }

        if (py >= list_y && py < list_y + zone_h) {
            int item_h = zone_h / ITEMS_PER_PAGE;
            int index =
                catalog_page * ITEMS_PER_PAGE +
                (py - list_y) / item_h;

            if (index >= 0 && index < catalogs_count) {
                if (catalogs[index].custom) {
                    OpenKeyboard(
                        "OPDS URL",
                        custom_opds_url,
                        1023,
                        1,
                        keyboard_opds_handler
                    );
                } else if (select_catalog(&catalogs[index])) {
                    Message(
                        ICON_INFORMATION,
                        "BookFerry",
                        "Библиотека изменена",
                        1600
                    );
                    app_mode = MODE_HOME;
                    draw_screen();
                } else {
                    Message(
                        ICON_ERROR,
                        "BookFerry",
                        "Не удалось сменить библиотеку",
                        3000
                    );
                    draw_screen();
                }
            }
            return;
        }
    }

    if (
        app_mode == MODE_ABOUT &&
        py >= main_rect.y + main_rect.h - button_h
    ) {
        app_mode = MODE_HOME;
        draw_screen();
    }
}

static void shutdown_downloads(void) {
    ClearTimer(download_poll_timer);
    ClearTimer(report_poll_timer);

    if (download_state.active) {
        close_download_session(true);
        remove(download_state.tmp_path);
        download_state.active = false;
    }

    if (report_session >= 0) {
        close_report_session(true);
    }
}

static int main_handler(int type, int par1, int par2) {
    switch (type) {
        case EVT_INIT: {
            int screen_w = ScreenWidth();
            int screen_h = ScreenHeight();
            int font_size =
                screen_w >= 1200 ? 48 :
                screen_w >= 1000 ? 42 : 32;

            font = OpenFont("DejaVu Sans", font_size, false);
            load_settings();

            memset(&download_state, 0, sizeof(download_state));
            download_state.session = -1;

            main_rect.y = screen_h * 7 / 100;
            main_rect.w = screen_w;
            main_rect.h =
                screen_h - main_rect.y - screen_h * 10 / 100;
            break;
        }

        case EVT_SHOW:
            if (!startup_synced) {
                if (ensure_user()) load_profile();
                startup_synced = true;
            }
            draw_screen();
            break;

        case EVT_POINTERDOWN:
            handle_tap(par1, par2);
            break;

        case EVT_EXIT:
            shutdown_downloads();
            CloseFont(font);
            break;
    }

    return 0;
}

int main(void) {
    InkViewMain(main_handler);
    return 0;
}