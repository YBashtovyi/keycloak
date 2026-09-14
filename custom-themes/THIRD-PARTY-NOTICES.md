# Компоненти теми КУБ

- Шаблони `login.ftl` і `template.ftl` адаптовано з Keycloak 23.0.7.
  Зміни стосуються компонування, брендингу, українських текстів і доступності.
  Ліцензія вихідного коду Keycloak: Apache-2.0, копія — `licenses/Apache-2.0.txt`.
  Джерело: https://github.com/keycloak/keycloak/tree/23.0.7/themes/src/main/resources/theme/base/login
- Український словник адаптовано з community-перекладів Keycloak; точну
  ревізію наведено в заголовках `messages_uk.properties` і `messages_en.properties`.
  Ліцензія: Apache-2.0.
- IBM Plex Sans, накреслення 400/500/600/700: Copyright © 2017 IBM Corp.,
  Reserved Font Name "Plex". Ліцензія SIL Open Font License 1.1 додається
  біля шрифтів: `kub/login/resources/fonts/OFL.txt`.
  Джерело ліцензії: https://github.com/IBM/plex/blob/master/LICENSE.txt
- Емблему КУБ надав замовник; прозорий фон підготовлено програмно.
  Ліцензії Keycloak та IBM Plex не поширюють права на використання бренду КУБ.
  Фавікон походить із бренд-ресурсів застосунку КУБ.

У JAR файли теми знаходяться під префіксом `theme/`, а цей файл і ліцензія
Apache-2.0 — у `META-INF/`.
