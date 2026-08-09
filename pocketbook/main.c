#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <inkview.h>

#define SERVER_URL "https://api.heartlab.app"

#define CONFIG_DIR  "/mnt/ext1/system/config/BookFerry"
#define CONFIG_FILE "/mnt/ext1/system/config/BookFerry/config.cfg"

#define MAX_ENTRIES 160
#define MAX_CATALOGS 20
#define ITEMS_PER_PAGE 5
#define URL_LEN 8192

enum {
    MODE_HOME = 0,
    MODE_RESULTS,
    MODE_ABOUT,
    MODE_CATALOGS
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

ifont *font;
irect main_rect;

char user_uid[64] = "";
char catalog_name[256] = "Не выбрана";
char custom_opds_url[1024] = "";
char search_text[256] = "";
char next_page_url[2048] = "";
char server_url[512] = DEFAULT_SERVER_URL;

BookEntry entries[MAX_ENTRIES];
CatalogEntry catalogs[MAX_CATALOGS];

int app_mode = MODE_HOME;
int entries_count = 0;
int current_page = 0;
int catalogs_count = 0;
int catalog_page = 0;
time_t last_tap_time = 0;
bool startup_synced = false;


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

static void clear_entries() {
    entries_count = 0;
    current_page = 0;
    next_page_url[0] = '\0';
    memset(entries, 0, sizeof(entries));
}

static void save_settings() {
    FILE *file;

    system("mkdir -p " CONFIG_DIR);

    file = fopen(CONFIG_FILE, "w");
    if (!file) return;

    fprintf(file, "%s\n", user_uid);
    fprintf(file, "%s\n", catalog_name);
    fprintf(file, "%s\n", custom_opds_url);
    fprintf(file, "%s\n", server_url)
    fclose(file);
}

static void load_settings() {
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
        safe_copy(
            server_url,
            DEFAULT_SERVER_URL,
            sizeof(server_url)
        );
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

static void refresh_library() {
    system("/ebrmain/bin/scanner.app >/dev/null 2>&1 &");
}

static bool register_user() {
    char url[URL_LEN];
    char *text;
    char *fields[5];
    int count;

    snprintf(
        url,
        sizeof(url),
        "%s/users/register?client_type=pocketbook&plain=1&ts=%ld",
        SERVER_URL,
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

static bool load_profile() {
    char url[URL_LEN];
    char *text;
    char *fields[6];
    int count;

    if (!user_uid[0]) return false;

    snprintf(
        url,
        sizeof(url),
        "%s/users/%s?plain=1",
        SERVER_URL,
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

static bool ensure_user() {
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

static bool load_catalogs() {
    char url[URL_LEN];
    char *text;
    char *line;

    snprintf(url, sizeof(url), "%s/catalogs?plain=1", SERVER_URL);

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
        SERVER_URL,
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
        SERVER_URL,
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

static void do_search() {
    char query[1024];
    char url[URL_LEN];

    if (!search_text[0] || !ensure_user()) return;

    clear_entries();
    url_encode(search_text, query, sizeof(query));

    snprintf(
        url,
        sizeof(url),
        "%s/search?uid=%s&query=%s&plain=1",
        SERVER_URL,
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

static bool load_next_page() {
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
        SERVER_URL,
        user_uid,
        query,
        page
    );

    if (!load_search_page(url, "Следующая страница...")) return false;
    return entries_count > old_count;
}

static void download_book_to_device(BookEntry *book) {
    char encoded_url[6144];
    char url[URL_LEN];
    char filename[256];
    char filepath[512];
    int size = 0;
    void *data;
    FILE *file;
    size_t written;

    if (!book || !book->url[0] || !user_uid[0]) return;

    url_encode(book->url, encoded_url, sizeof(encoded_url));

    snprintf(
        url,
        sizeof(url),
        "%s/download?uid=%s&url=%s",
        SERVER_URL,
        user_uid,
        encoded_url
    );

    show_progress("Скачивание EPUB...");
    data = QuickDownload(url, &size, 120);

    if (
        !data ||
        size < 2 ||
        ((unsigned char *)data)[0] != 'P' ||
        ((unsigned char *)data)[1] != 'K'
    ) {
        if (data) free(data);
        Message(
            ICON_ERROR,
            "BookFerry",
            "Не удалось скачать EPUB",
            3000
        );
        return;
    }

    system("mkdir -p /mnt/ext1/Books");

    snprintf(
        filename,
        sizeof(filename),
        "%s - %s",
        book->author,
        book->title
    );
    sanitize_filename(filename);
    truncate_utf8(filename, 220);
    strncat(filename, ".epub", sizeof(filename) - strlen(filename) - 1);

    snprintf(
        filepath,
        sizeof(filepath),
        "/mnt/ext1/Books/%s",
        filename
    );

    file = fopen(filepath, "wb");
    if (!file) {
        free(data);
        Message(
            ICON_ERROR,
            "BookFerry",
            "Не удалось сохранить файл",
            3000
        );
        return;
    }

    written = fwrite(data, 1, size, file);
    fclose(file);
    free(data);

    if (written != (size_t)size) {
        remove(filepath);
        Message(
            ICON_ERROR,
            "BookFerry",
            "Ошибка записи файла",
            3000
        );
        return;
    }

    Message(
        ICON_INFORMATION,
        "BookFerry",
        "EPUB скачан в папку Books",
        2200
    );
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

static void draw_screen() {
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
        int refresh_y = about_y - button_h - spacing;

        DrawRect(x, y, width, input_h, BLACK);
        DrawString(x + 20, y + input_h / 4 - font->height / 2, "Библиотека:");
        DrawString(x + 20, y + input_h * 3 / 4 - font->height / 2, catalog_name);
        y += input_h + spacing;

        DrawRect(x, y, width, input_h, BLACK);
        DrawString(x + 20, y + input_h / 4 - font->height / 2, "Название или автор:");
        DrawString(x + 20, y + input_h * 3 / 4 - font->height / 2, search_text);
        y += input_h + spacing;

        DrawRect(x, y, width, button_h, BLACK);
        DrawString(
            x + (width - StringWidth(">>> НАЧАТЬ ПОИСК <<<")) / 2,
            y + (button_h - font->height) / 2,
            ">>> НАЧАТЬ ПОИСК <<<"
        );

        DrawRect(x, refresh_y, width, button_h, BLACK);
        DrawString(
            x + (width - StringWidth("[ Обн. библиотеку ]")) / 2,
            refresh_y + (button_h - font->height) / 2,
            "[ Обн. библиотеку ]"
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

        total_pages = (entries_count + ITEMS_PER_PAGE - 1) / ITEMS_PER_PAGE;
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
            main_rect.y + main_rect.h - button_h - font->height - 25,
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
        DrawString(x, y, "Версия: 2.0");
        y += font->height + 10;
        DrawString(x, y, "Поиск через сервер BookFerry");
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
    }

    FullUpdate();
}

static void keyboard_search_handler(char *text) {
    if (text) safe_copy(search_text, text, sizeof(search_text));
    draw_screen();
}

static void keyboard_opds_handler(char *text) {
    if (!text || !text[0]) {
        draw_screen();
        return;
    }

    if (select_custom_opds(text)) {
        Message(ICON_INFORMATION, "BookFerry", "OPDS подключён", 1800);
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

    if (time(NULL) - last_tap_time < 1) return;
    last_tap_time = time(NULL);
    {
    char debug[256];

    int first_y = main_rect.y + spacing;
    int second_y = first_y + input_h + spacing;

    snprintf(
        debug,
        sizeof(debug),
        "tap y=%d\nlib: %d-%d\nsearch: %d-%d",
        py,
        first_y,
        first_y + input_h,
        second_y,
        second_y + input_h
    );

    Message(
        ICON_INFORMATION,
        "DEBUG TAP",
        debug,
        3000
    );
}

    if (app_mode == MODE_HOME) {
        int y = main_rect.y + spacing;
        int about_y = main_rect.y + main_rect.h - button_h - spacing;
        int refresh_y = about_y - button_h - spacing;

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
            py >= refresh_y && py <= refresh_y + button_h
        ) {
            refresh_library();
            Message(
                ICON_INFORMATION,
                "Готово",
                "Сканирование библиотеки запущено",
                2200
            );
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
                if (current_page > 0) current_page--;
                else {
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
                download_book_to_device(&entries[index]);
                draw_screen();
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
                if (catalog_page < total - 1) catalog_page++;
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
            CloseFont(font);
            break;
    }

    return 0;
}

int main() {
    InkViewMain(main_handler);
    return 0;
}
