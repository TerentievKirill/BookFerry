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
#define URL_LEN 4096
#define TOKEN_LEN 4096
#define UID_LEN 64

#define MODE_HOME 0
#define MODE_RESULTS 1
#define MODE_ABOUT 2
#define MODE_CATALOGS 3

typedef struct {
    char title[256];
    char author[256];
    char token[TOKEN_LEN];
} BookEntry;

typedef struct {
    int id;
    bool custom;
    char name[256];
} CatalogEntry;

ifont *font;
irect main_rect;

char device_uid[UID_LEN] = "";
char catalog_name[256] = "Не выбрана";
char custom_opds_url[1024] = "";
char search_text[256] = "";
char next_page_token[TOKEN_LEN] = "";

int app_mode = MODE_HOME;
int entries_count = 0;
int current_page = 0;
int catalogs_count = 0;
int catalog_page = 0;
time_t last_tap_time = 0;

BookEntry entries[MAX_ENTRIES];
CatalogEntry catalogs[MAX_CATALOGS];

void load_settings();
void save_settings();
void draw_screen();
void do_search();
void keyboard_search_handler(char *text);
void keyboard_opds_handler(char *text);
void clear_entries();
void show_progress_bar(const char *message);
void refresh_library();
void download_selected_book(BookEntry *entry);
void handle_tap(int x, int y);
int main_handler(int type, int par1, int par2);

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

        if (src[i] == '+') dst[j++] = ' ';
        else dst[j++] = src[i];
        i++;
    }

    dst[j] = '\0';
}

static void url_encode_component(const char *src, char *dst, int dst_len) {
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
            dst[j++] = hex[(c >> 4) & 0x0F];
            dst[j++] = hex[c & 0x0F];
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

static char *http_get_text(const char *url, int timeout_seconds) {
    int size = 0;
    void *raw = QuickDownload(url, &size, timeout_seconds);
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

static void sanitize_filename(char *filename) {
    int i;

    if (!filename) return;

    for (i = 0; filename[i]; i++) {
        unsigned char c = (unsigned char)filename[i];
        if (strchr("/\\:*?\"|<>", c) || c < 32) {
            filename[i] = '_';
        }
    }
}

void clear_entries() {
    entries_count = 0;
    current_page = 0;
    next_page_token[0] = '\0';
    memset(entries, 0, sizeof(entries));
}

void save_settings() {
    FILE *file;

    system("mkdir -p " CONFIG_DIR);

    file = fopen(CONFIG_FILE, "w");
    if (!file) return;

    fprintf(file, "%s\n", device_uid);
    fprintf(file, "%s\n", catalog_name);
    fprintf(file, "%s\n", custom_opds_url);
    fclose(file);
}

void load_settings() {
    FILE *file = fopen(CONFIG_FILE, "r");

    if (!file) return;

    if (fgets(device_uid, sizeof(device_uid), file)) {
        device_uid[strcspn(device_uid, "\r\n")] = '\0';
    }

    if (fgets(catalog_name, sizeof(catalog_name), file)) {
        catalog_name[strcspn(catalog_name, "\r\n")] = '\0';
    }

    if (fgets(custom_opds_url, sizeof(custom_opds_url), file)) {
        custom_opds_url[strcspn(custom_opds_url, "\r\n")] = '\0';
    }

    fclose(file);
}

void show_progress_bar(const char *message) {
    int win_w = main_rect.w * 70 / 100;
    int win_h = main_rect.h * 15 / 100;
    int win_x = main_rect.x + (main_rect.w - win_w) / 2;
    int win_y = main_rect.y + (main_rect.h - win_h) / 2;

    FillArea(win_x, win_y, win_w, win_h, WHITE);
    DrawRect(win_x, win_y, win_w, win_h, BLACK);
    DrawString(
        win_x + (win_w - StringWidth(message)) / 2,
        win_y + (win_h - font->height) / 2,
        message
    );
    FullUpdate();
}

void refresh_library() {
    system("/ebrmain/bin/scanner.app >/dev/null 2>&1 &");
}

static bool register_device() {
    char url[URL_LEN];
    char *text;
    char *fields[5];
    int count;
    char encoded_name[768];

    snprintf(
        url,
        sizeof(url),
        "%s/pocketbook/register?ts=%ld",
        SERVER_URL,
        (long)time(NULL)
    );

    show_progress_bar("Регистрация...");
    text = http_get_text(url, 30);
    if (!text) return false;

    text[strcspn(text, "\r\n")] = '\0';
    count = split_fields(text, fields, 5);

    if (count < 4 || strcmp(fields[0], "UID") != 0) {
        free(text);
        return false;
    }

    safe_copy(device_uid, fields[1], sizeof(device_uid));
    safe_copy(encoded_name, fields[3], sizeof(encoded_name));
    percent_decode(encoded_name, catalog_name, sizeof(catalog_name));
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
    char mode[32];

    if (!device_uid[0]) return false;

    snprintf(
        url,
        sizeof(url),
        "%s/pocketbook/%s/profile",
        SERVER_URL,
        device_uid
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
    safe_copy(mode, fields[3], sizeof(mode));

    if (strcmp(mode, "custom") == 0) {
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

static bool ensure_device() {
    if (!device_uid[0]) {
        if (!register_device()) {
            Message(
                ICON_ERROR,
                "BookFerry",
                "Не удалось зарегистрировать устройство",
                3000
            );
            return false;
        }
    }

    return true;
}

static bool load_catalogs() {
    char url[URL_LEN];
    char *text;
    char *line;

    snprintf(url, sizeof(url), "%s/pocketbook/catalogs", SERVER_URL);

    show_progress_bar("Библиотеки...");
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
            catalog->custom = false;
            percent_decode(
                fields[2],
                catalog->name,
                sizeof(catalog->name)
            );
        } else if (count >= 2 && strcmp(fields[0], "CUSTOM") == 0) {
            CatalogEntry *catalog = &catalogs[catalogs_count++];
            catalog->id = 0;
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

static bool set_catalog(CatalogEntry *catalog) {
    char url[URL_LEN];
    char *text;
    char *fields[4];
    int count;

    if (!catalog || catalog->custom || !device_uid[0]) return false;

    snprintf(
        url,
        sizeof(url),
        "%s/pocketbook/%s/catalog/%d",
        SERVER_URL,
        device_uid,
        catalog->id
    );

    show_progress_bar("Сохраняю...");
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
    save_settings();
    clear_entries();

    free(text);
    return true;
}

static bool set_custom_opds(const char *opds_url) {
    char url[URL_LEN];
    char encoded_url[3072];
    char *text;
    char *fields[4];
    int count;

    if (!opds_url || !opds_url[0] || !device_uid[0]) return false;

    url_encode_component(opds_url, encoded_url, sizeof(encoded_url));

    snprintf(
        url,
        sizeof(url),
        "%s/pocketbook/%s/opds?url=%s",
        SERVER_URL,
        device_uid,
        encoded_url
    );

    show_progress_bar("Проверяю OPDS...");
    text = http_get_text(url, 60);
    if (!text) return false;

    text[strcspn(text, "\r\n")] = '\0';
    count = split_fields(text, fields, 4);

    if (count < 3 || strcmp(fields[0], "OK") != 0) {
        free(text);
        return false;
    }

    percent_decode(fields[2], catalog_name, sizeof(catalog_name));
    safe_copy(custom_opds_url, opds_url, sizeof(custom_opds_url));
    save_settings();
    clear_entries();

    free(text);
    return true;
}

static bool parse_search_response(char *text) {
    char *line = text;
    bool found_any = false;

    next_page_token[0] = '\0';

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
            BookEntry *entry = &entries[entries_count];
            memset(entry, 0, sizeof(BookEntry));

            percent_decode(
                fields[1],
                entry->title,
                sizeof(entry->title)
            );
            percent_decode(
                fields[2],
                entry->author,
                sizeof(entry->author)
            );
            safe_copy(entry->token, fields[3], sizeof(entry->token));

            if (entry->title[0] && entry->token[0]) {
                if (!entry->author[0]) {
                    safe_copy(
                        entry->author,
                        "Неизвестный автор",
                        sizeof(entry->author)
                    );
                }
                entries_count++;
                found_any = true;
            }
        } else if (count >= 2 && strcmp(fields[0], "NEXT") == 0) {
            safe_copy(
                next_page_token,
                fields[1],
                sizeof(next_page_token)
            );
        }

        line = eol ? eol + 1 : NULL;
    }

    return found_any;
}

static bool load_search_page(const char *url, const char *message) {
    char *text;
    bool result;

    if (message && message[0]) show_progress_bar(message);

    text = http_get_text(url, 90);
    if (!text) return false;

    result = parse_search_response(text);
    free(text);
    return result;
}

void do_search() {
    char url[URL_LEN];
    char encoded_query[1024];

    if (!search_text[0]) return;
    if (!ensure_device()) {
        draw_screen();
        return;
    }

    clear_entries();
    url_encode_component(
        search_text,
        encoded_query,
        sizeof(encoded_query)
    );

    snprintf(
        url,
        sizeof(url),
        "%s/pocketbook/%s/search?q=%s",
        SERVER_URL,
        device_uid,
        encoded_query
    );

    if (!load_search_page(url, "Поиск...")) {
        Message(
            ICON_ERROR,
            "BookFerry",
            "Ничего не найдено или сервер недоступен",
            3000
        );
        draw_screen();
        return;
    }

    app_mode = MODE_RESULTS;
    current_page = 0;
    draw_screen();
}

void download_selected_book(BookEntry *entry) {
    char url[URL_LEN + TOKEN_LEN];
    char filepath[768];
    char filename[512];
    int size = 0;
    void *data;
    FILE *file;

    if (!entry || !entry->token[0] || !device_uid[0]) return;

    snprintf(
        url,
        sizeof(url),
        "%s/pocketbook/%s/download/%s",
        SERVER_URL,
        device_uid,
        entry->token
    );

    show_progress_bar("Скачивание EPUB...");
    data = QuickDownload(url, &size, 120);

    if (!data || size <= 0) {
        if (data) free(data);
        Message(
            ICON_ERROR,
            "BookFerry",
            "Не удалось скачать книгу",
            3000
        );
        draw_screen();
        return;
    }

    system("mkdir -p /mnt/ext1/Books");

    snprintf(
        filename,
        sizeof(filename),
        "%s - %s.epub",
        entry->author,
        entry->title
    );
    sanitize_filename(filename);

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
        draw_screen();
        return;
    }

    fwrite(data, 1, size, file);
    fclose(file);
    free(data);

    Message(
        ICON_INFORMATION,
        "BookFerry",
        "EPUB скачан в папку Books",
        2500
    );
    draw_screen();
}

static void draw_bottom_nav(
    int x_start,
    int w_content,
    int button_h,
    int spacing,
    const char *center_text
) {
    int btn_y = (main_rect.y + main_rect.h) - button_h;
    int btn_w = (w_content - (spacing * 2)) / 3;

    DrawRect(x_start, btn_y, btn_w, button_h, BLACK);
    DrawString(
        x_start + (btn_w - StringWidth("<")) / 2,
        btn_y + (button_h - font->height) / 2,
        "<"
    );

    DrawRect(
        x_start + btn_w + spacing,
        btn_y,
        btn_w,
        button_h,
        BLACK
    );
    DrawString(
        x_start + btn_w + spacing +
            (btn_w - StringWidth(center_text)) / 2,
        btn_y + (button_h - font->height) / 2,
        center_text
    );

    DrawRect(
        x_start + (btn_w + spacing) * 2,
        btn_y,
        btn_w,
        button_h,
        BLACK
    );
    DrawString(
        x_start + (btn_w + spacing) * 2 +
            (btn_w - StringWidth(">")) / 2,
        btn_y + (button_h - font->height) / 2,
        ">"
    );
}

void draw_screen() {
    int side_margin;
    int x_start;
    int w_content;
    int input_h;
    int button_h;
    int spacing;
    int y_cursor;

    ClearScreen();
    SetFont(font, BLACK);

    side_margin = main_rect.w * 5 / 100;
    x_start = main_rect.x + side_margin;
    w_content = main_rect.w - (side_margin * 2);
    input_h = main_rect.h * 11 / 100;
    button_h = main_rect.h * 9 / 100;
    spacing = main_rect.h * 3 / 100;
    y_cursor = main_rect.y + spacing;

    if (app_mode == MODE_HOME) {
        int about_y;
        int refresh_y;
        const char *search_button = ">>> НАЧАТЬ ПОИСК <<<";

        DrawRect(x_start, y_cursor, w_content, input_h, BLACK);
        DrawString(
            x_start + 20,
            y_cursor + (input_h / 4) - (font->height / 2),
            "Библиотека:"
        );
        DrawString(
            x_start + 20,
            y_cursor + (input_h * 3 / 4) - (font->height / 2),
            catalog_name
        );
        y_cursor += input_h + spacing;

        DrawRect(x_start, y_cursor, w_content, input_h, BLACK);
        DrawString(
            x_start + 20,
            y_cursor + (input_h / 4) - (font->height / 2),
            "Название или автор:"
        );
        DrawString(
            x_start + 20,
            y_cursor + (input_h * 3 / 4) - (font->height / 2),
            search_text
        );
        y_cursor += input_h + spacing;

        DrawRect(x_start, y_cursor, w_content, button_h, BLACK);
        DrawString(
            x_start + (w_content - StringWidth(search_button)) / 2,
            y_cursor + (button_h - font->height) / 2,
            search_button
        );

        about_y = (main_rect.y + main_rect.h) - button_h - spacing;
        refresh_y = about_y - button_h - spacing;

        DrawRect(x_start, refresh_y, w_content, button_h, BLACK);
        DrawString(
            x_start +
                (w_content - StringWidth("[ Обн. библиотеку ]")) / 2,
            refresh_y + (button_h - font->height) / 2,
            "[ Обн. библиотеку ]"
        );

        DrawRect(x_start, about_y, w_content, button_h, BLACK);
        DrawString(
            x_start + (w_content - StringWidth("[ О программе ]")) / 2,
            about_y + (button_h - font->height) / 2,
            "[ О программе ]"
        );
    } else if (app_mode == MODE_RESULTS) {
        int list_zone_h = main_rect.h * 60 / 100;
        int item_h = list_zone_h / ITEMS_PER_PAGE;
        int start_res = current_page * ITEMS_PER_PAGE;
        int end_res = start_res + ITEMS_PER_PAGE;
        int total_pages;
        int i;
        char page_status[128];

        if (end_res > entries_count) end_res = entries_count;

        for (i = start_res; i < end_res; i++) {
            DrawString(
                x_start + 10,
                y_cursor + (item_h / 4) - (font->height / 2),
                entries[i].title
            );
            DrawString(
                x_start + 10,
                y_cursor + (item_h * 3 / 4) - (font->height / 2),
                entries[i].author
            );
            DrawLine(
                x_start,
                y_cursor + item_h - 2,
                x_start + w_content,
                y_cursor + item_h - 2,
                BLACK
            );
            y_cursor += item_h;
        }

        total_pages =
            (entries_count + ITEMS_PER_PAGE - 1) / ITEMS_PER_PAGE;
        if (total_pages < 1) total_pages = 1;

        if (next_page_token[0]) {
            snprintf(
                page_status,
                sizeof(page_status),
                "Найдено: %d+ | Стр. %d/%d",
                entries_count,
                current_page + 1,
                total_pages
            );
        } else {
            snprintf(
                page_status,
                sizeof(page_status),
                "Найдено: %d | Стр. %d/%d",
                entries_count,
                current_page + 1,
                total_pages
            );
        }

        DrawString(
            x_start,
            (main_rect.y + main_rect.h) -
                button_h - font->height - 25,
            page_status
        );

        draw_bottom_nav(
            x_start,
            w_content,
            button_h,
            spacing,
            "Домой"
        );
    } else if (app_mode == MODE_CATALOGS) {
        int list_top;
        int list_zone_h;
        int item_h;
        int start_item;
        int end_item;
        int total_pages;
        int i;
        char page_status[96];

        DrawString(x_start, y_cursor, "Выберите библиотеку:");
        y_cursor += font->height + spacing;
        list_top = y_cursor;
        list_zone_h = main_rect.h * 52 / 100;
        item_h = list_zone_h / ITEMS_PER_PAGE;
        start_item = catalog_page * ITEMS_PER_PAGE;
        end_item = start_item + ITEMS_PER_PAGE;
        if (end_item > catalogs_count) end_item = catalogs_count;

        for (i = start_item; i < end_item; i++) {
            DrawString(
                x_start + 10,
                y_cursor + (item_h - font->height) / 2,
                catalogs[i].name
            );
            DrawLine(
                x_start,
                y_cursor + item_h - 2,
                x_start + w_content,
                y_cursor + item_h - 2,
                BLACK
            );
            y_cursor += item_h;
        }

        total_pages =
            (catalogs_count + ITEMS_PER_PAGE - 1) / ITEMS_PER_PAGE;
        if (total_pages < 1) total_pages = 1;

        snprintf(
            page_status,
            sizeof(page_status),
            "Стр. %d/%d",
            catalog_page + 1,
            total_pages
        );

        DrawString(
            x_start,
            list_top + list_zone_h + spacing,
            page_status
        );

        draw_bottom_nav(
            x_start,
            w_content,
            button_h,
            spacing,
            "Домой"
        );
    } else if (app_mode == MODE_ABOUT) {
        int btn_y;

        DrawString(x_start, y_cursor, "О программе:");
        y_cursor += font->height * 2;
        DrawString(x_start, y_cursor, "BookFerry для PocketBook");
        y_cursor += font->height + 10;
        DrawString(x_start, y_cursor, "Версия: 2.0");
        y_cursor += font->height + 10;
        DrawString(x_start, y_cursor, "Поиск через сервер BookFerry");
        y_cursor += font->height + 10;
        DrawString(x_start, y_cursor, "Кирилл Т");
        y_cursor += font->height + 10;
        DrawString(x_start, y_cursor, "kirillterentiev@gmail.com");

        btn_y = (main_rect.y + main_rect.h) - button_h;
        DrawRect(x_start, btn_y, w_content, button_h, BLACK);
        DrawString(
            x_start + (w_content - StringWidth("Назад")) / 2,
            btn_y + (button_h - font->height) / 2,
            "Назад"
        );
    }

    FullUpdate();
}

void keyboard_search_handler(char *text) {
    if (text) {
        safe_copy(search_text, text, sizeof(search_text));
    }
    draw_screen();
}

void keyboard_opds_handler(char *text) {
    if (!text || !text[0]) {
        draw_screen();
        return;
    }

    if (set_custom_opds(text)) {
        Message(
            ICON_INFORMATION,
            "BookFerry",
            "OPDS подключён",
            2000
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

void handle_tap(int x, int y) {
    int side_margin;
    int x_start;
    int w_content;
    int input_h;
    int button_h;
    int spacing;

    if (time(NULL) - last_tap_time < 1) return;
    last_tap_time = time(NULL);

    side_margin = main_rect.w * 5 / 100;
    x_start = main_rect.x + side_margin;
    w_content = main_rect.w - (side_margin * 2);
    input_h = main_rect.h * 11 / 100;
    button_h = main_rect.h * 9 / 100;
    spacing = main_rect.h * 3 / 100;

    if (app_mode == MODE_HOME) {
        int y_cursor = main_rect.y + spacing;
        int about_y =
            (main_rect.y + main_rect.h) - button_h - spacing;
        int refresh_y = about_y - button_h - spacing;

        if (
            x >= x_start && x <= x_start + w_content &&
            y >= y_cursor && y <= y_cursor + input_h
        ) {
            if (!ensure_device()) {
                draw_screen();
                return;
            }

            if (load_catalogs()) {
                app_mode = MODE_CATALOGS;
                draw_screen();
            } else {
                Message(
                    ICON_ERROR,
                    "BookFerry",
                    "Не удалось получить библиотеки",
                    3000
                );
                draw_screen();
            }
            return;
        }

        y_cursor += input_h + spacing;

        if (
            x >= x_start && x <= x_start + w_content &&
            y >= y_cursor && y <= y_cursor + input_h
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

        y_cursor += input_h + spacing;

        if (
            x >= x_start && x <= x_start + w_content &&
            y >= y_cursor && y <= y_cursor + button_h &&
            search_text[0]
        ) {
            do_search();
            return;
        }

        if (
            x >= x_start && x <= x_start + w_content &&
            y >= refresh_y && y <= refresh_y + button_h
        ) {
            refresh_library();
            Message(
                ICON_INFORMATION,
                "Готово",
                "Сканирование библиотеки запущено",
                2500
            );
            draw_screen();
            return;
        }

        if (
            x >= x_start && x <= x_start + w_content &&
            y >= about_y && y <= about_y + button_h
        ) {
            app_mode = MODE_ABOUT;
            draw_screen();
            return;
        }
    } else if (app_mode == MODE_RESULTS) {
        int btn_y = (main_rect.y + main_rect.h) - button_h;
        int btn_w = (w_content - (spacing * 2)) / 3;
        int list_top = main_rect.y + spacing;
        int list_zone_h = main_rect.h * 60 / 100;

        if (y >= btn_y && y <= btn_y + button_h) {
            if (x >= x_start && x <= x_start + btn_w) {
                if (current_page > 0) current_page--;
                else {
                    app_mode = MODE_HOME;
                    clear_entries();
                }
            } else if (
                x >= x_start + btn_w + spacing &&
                x <= x_start + btn_w + spacing + btn_w
            ) {
                app_mode = MODE_HOME;
                clear_entries();
            } else if (
                x >= x_start + (btn_w + spacing) * 2 &&
                x <= x_start + w_content
            ) {
                int total_pages =
                    (entries_count + ITEMS_PER_PAGE - 1) /
                    ITEMS_PER_PAGE;

                if (current_page < total_pages - 1) {
                    current_page++;
                } else if (
                    next_page_token[0] &&
                    entries_count < MAX_ENTRIES
                ) {
                    char url[URL_LEN + TOKEN_LEN];
                    char encoded_query[1024];
                    int old_count = entries_count;

                    url_encode_component(
                        search_text,
                        encoded_query,
                        sizeof(encoded_query)
                    );

                    snprintf(
                        url,
                        sizeof(url),
                        "%s/pocketbook/%s/search?q=%s&page=%s",
                        SERVER_URL,
                        device_uid,
                        encoded_query,
                        next_page_token
                    );

                    if (
                        load_search_page(url, "Следующая страница...") &&
                        entries_count > old_count
                    ) {
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

        if (y >= list_top && y < list_top + list_zone_h) {
            int item_h = list_zone_h / ITEMS_PER_PAGE;
            int idx =
                current_page * ITEMS_PER_PAGE +
                (y - list_top) / item_h;

            if (idx >= 0 && idx < entries_count) {
                download_selected_book(&entries[idx]);
            }
            return;
        }
    } else if (app_mode == MODE_CATALOGS) {
        int btn_y = (main_rect.y + main_rect.h) - button_h;
        int btn_w = (w_content - (spacing * 2)) / 3;
        int list_top =
            main_rect.y + spacing + font->height + spacing;
        int list_zone_h = main_rect.h * 52 / 100;

        if (y >= btn_y && y <= btn_y + button_h) {
            if (x >= x_start && x <= x_start + btn_w) {
                if (catalog_page > 0) catalog_page--;
            } else if (
                x >= x_start + btn_w + spacing &&
                x <= x_start + btn_w + spacing + btn_w
            ) {
                app_mode = MODE_HOME;
            } else if (
                x >= x_start + (btn_w + spacing) * 2 &&
                x <= x_start + w_content
            ) {
                int total_pages =
                    (catalogs_count + ITEMS_PER_PAGE - 1) /
                    ITEMS_PER_PAGE;
                if (catalog_page < total_pages - 1) catalog_page++;
            }

            draw_screen();
            return;
        }

        if (y >= list_top && y < list_top + list_zone_h) {
            int item_h = list_zone_h / ITEMS_PER_PAGE;
            int idx =
                catalog_page * ITEMS_PER_PAGE +
                (y - list_top) / item_h;

            if (idx >= 0 && idx < catalogs_count) {
                if (catalogs[idx].custom) {
                    OpenKeyboard(
                        "OPDS URL",
                        custom_opds_url,
                        1023,
                        1,
                        keyboard_opds_handler
                    );
                } else if (set_catalog(&catalogs[idx])) {
                    Message(
                        ICON_INFORMATION,
                        "BookFerry",
                        "Библиотека изменена",
                        1800
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
    } else if (app_mode == MODE_ABOUT) {
        if (y >= (main_rect.y + main_rect.h) - button_h) {
            app_mode = MODE_HOME;
            draw_screen();
        }
    }
}

int main_handler(int type, int par1, int par2) {
    switch (type) {
        case EVT_INIT: {
            int screen_w = ScreenWidth();
            int screen_h = ScreenHeight();
            int font_size =
                (screen_w >= 1200) ? 48 :
                (screen_w >= 1000) ? 42 : 32;

            font = OpenFont("DejaVu Sans", font_size, false);
            load_settings();

            main_rect.y = screen_h * 7 / 100;
            main_rect.w = screen_w;
            main_rect.h =
                screen_h - main_rect.y - (screen_h * 10 / 100);
            break;
        }

        case EVT_SHOW:
            if (ensure_device()) {
                load_profile();
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
