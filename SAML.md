# Native SAML acceptance

## Результат 19 ноября 2026

Стенд использовал официальный образ grafana/grafana-enterprise:11.5.2, Keycloak 26.2.5 и временный клиент SAML. Grafana получила метаданные IdP, сертификат и ключ SP, настройку включения SAML и сопоставление значения Viewer. Проверки IdP и Grafana запускались раздельно и повторялись в общей процедуре.

| Сценарий | Что удалось наблюдать |
|---|---|
| Keycloak публикует метаданные IdP | Получен XML с entityID тестового realm, адресом POST SSO и сертификатом. |
| Keycloak выдаёт утверждение | По тестовому AuthnRequest браузер прошёл вход. Перехвачен POST, адресованный ACS. Проверены Destination, Audience, InResponseTo, значения login, email, role=Viewer и наличие элемента XML Signature. Криптографическую проверку этой подписи со стороны SP данный тест не выполняет. |
| Доступность SAML в Grafana | Enterprise API сообщил о неактивной лицензии. GET /login/saml дал 302 на /login. GET /saml/metadata также дал 302 на экран входа. XML метаданных SP не получен. |
| Вход в Grafana и роль Viewer | Не пройден. Grafana не открыла нативный SAML-поток до обмена с IdP. Значение Viewer в утверждении Keycloak ещё не подтверждает роль в организации Grafana. |
| Экспорт, повторное использование, истечение | Не выполнялись под SAML. Grafana не выдала сессию, с которой можно провести эти три проверки. |

[Свидетельство запуска](integration/evidence/saml-enterprise-11.5.2.json). Отдельная [матрица OIDC](COMPATIBILITY.md) описывает результаты с другим протоколом. Нативная интеграция SAML предусмотрена в Grafana Enterprise и Grafana Cloud. [Документация Grafana](https://grafana.com/docs/grafana/latest/setup-grafana/configure-access/configure-authentication/saml/).

## Как повторить

Понадобятся Docker, OpenSSL и Python-окружение для [браузерного экспорта](BROWSER.md). Используйте установленный Chrome с --channel chrome либо Chromium из Playwright без этой опции.

```sh
python integration/saml_idp.py --channel chrome
python integration/saml_check.py /tmp/panel2series-saml-001 --channel chrome
```

Первая команда проверяет выдачу утверждения на стороне Keycloak и перехватывает POST до доставки. Вторая поднимает отдельный экземпляр Grafana, проверяет нативные endpoints и пишет evidence.json в новый каталог. Если SP не отдаёт метаданные, она завершается с ненулевым кодом. Параметры сервиса, тестовый пароль, сессия, ключи и контейнеры являются временными.

Для положительной приёмки нужен тестовый экземпляр с действующей лицензией на SAML. Для изолированного контейнера передайте путь к файлу лицензии. Имя хоста, схема и порт должны соответствовать разрешённому root_url. HTTPS-пример предполагает тестовое имя, которое на рабочей станции разрешается в 127.0.0.1, свободный порт, PEM-сертификат этого имени и доверие к его CA у Python и браузерного окружения.

```sh
python integration/saml_check.py /tmp/panel2series-saml-002 --channel chrome \
  --license-file "$SAML_LICENSE_FILE" --port 8443 --tls-host grafana-saml.example.test \
  --tls-cert "$SAML_TLS_CERT" --tls-key "$SAML_TLS_KEY"
```

После получения настоящих метаданных SP тест должен проверить пользователя reader и роль Viewer через API Grafana, сопоставить точки 2, 7, 4 с эталоном, повторить выгрузку из нового процесса с сохранённой сессией, проверить CSV и PNG. После двухминутного срока Grafana должна вернуть 401 для последней сохранённой cookie, а CLI — завершиться с ошибкой без выходного файла. Только запуск с этими проверками закрывает приёмку.

Для интерактивной работы с настроенной Grafana выберите в профиле входа `"provider": "saml"` либо передайте `--provider saml`. В браузере открывается /login/saml. Если параметр опущен, используется прежний OIDC-путь. [Настройки входа](AUTH.md).
