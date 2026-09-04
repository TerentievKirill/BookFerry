import { expect, test } from '@playwright/test';

const registeredUser = {
  id: 1,
  uid: 'web-test-user',
  client_type: 'web',
  external_id: null,
  catalog_id: 1,
  opds_url: 'https://example.test/opds',
  emails: null,
  subject: null,
  created_at: '2026-09-04 00:00:00',
  last_seen_at: '2026-09-04 00:00:00',
};

test('shows the book search form', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveTitle('BookFerry Web');
  await expect(page.getByRole('heading', { name: 'BookFerry' })).toBeVisible();
  await expect(page.getByLabel('Название или автор')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Найти' })).toBeVisible();
});

test('searches books and renders results', async ({ page }) => {
  await page.route('**/users/register?client_type=web', async (route) => {
    await route.fulfill({ json: registeredUser });
  });

  await page.route('**/search?*', async (route) => {
    const requestUrl = new URL(route.request().url());

    expect(requestUrl.searchParams.get('query')).toBe('Лем');
    expect(requestUrl.searchParams.get('uid')).toBe('web-test-user');

    await route.fulfill({
      json: {
        books: [
          {
            title: 'Солярис',
            author: 'Станислав Лем',
            url: 'https://example.test/solaris.epub',
          },
          {
            title: 'Эдем',
            author: 'Станислав Лем',
            url: 'https://example.test/eden.epub',
          },
        ],
        next_page_url: null,
      },
    });
  });

  await page.goto('/');
  await page.getByLabel('Название или автор').fill('Лем');
  await page.getByRole('button', { name: 'Найти' }).click();

  await expect(page.getByRole('status')).toHaveText('Найдено: 2');
  await expect(page.getByTestId('book-card')).toHaveCount(2);
  await expect(page.getByRole('heading', { name: 'Солярис' })).toBeVisible();
  await expect(page.getByText('Станислав Лем')).toHaveCount(2);

  const download = page
    .getByTestId('book-card')
    .filter({ hasText: 'Солярис' })
    .getByRole('link', { name: 'Скачать EPUB' });

  await expect(download).toHaveAttribute(
    'href',
    '/download?uid=web-test-user&url=https%3A%2F%2Fexample.test%2Fsolaris.epub',
  );
});

test('shows an error when search API fails', async ({ page }) => {
  await page.route('**/users/register?client_type=web', async (route) => {
    await route.fulfill({ json: registeredUser });
  });

  await page.route('**/search?*', async (route) => {
    await route.fulfill({
      status: 502,
      json: { detail: 'Catalog is unavailable' },
    });
  });

  await page.goto('/');
  await page.getByLabel('Название или автор').fill('test');
  await page.getByRole('button', { name: 'Найти' }).click();

  await expect(page.getByRole('status')).toHaveText('Не удалось выполнить поиск.');
  await expect(page.getByTestId('book-card')).toHaveCount(0);
});
