# Keycloak 23.0.7: нове dev-середовище auth2.kub.army

Дата підготовки: 2026-09-14. Це ранбук для виконання DevOps у Bash/WSL.
Він підготовлений за локальним кодом `Beacons.Terraform` та документацією
Keycloak **23.0.7**. Фактичний стан AWS/EKS не перевірявся; команди розгортання
не виконувались. Приклади нижче потребують заповнення параметрів середовища.

## 1. Межі та рішення перед початком

Створюємо новий екземпляр Keycloak, порожню БД та realm; не копіюємо prod-БД,
користувачів, паролі, signing keys чи client secrets із rel. Наявні
`auth.kub.army` та локальні сервери не змінюємо. Підключення теми описане
окремо в [DEVOPS.md](DEVOPS.md).

Підтверджено власником: наявні **dev EKS і dev RDS**, окремий namespace та
нова БД з окремою роллю; **публічний вхід та обмежена адмінка**.
Нижче — internet-facing ALB, DNS only у Cloudflare, `/admin` доступний лише
з погодженого зовнішнього CIDR адміністративної мережі/VPN.

| Параметр | Значення / рішення |
|---|---|
| AWS account | dev, `546518615280`; перевірити через STS |
| AWS profile / region | `mayaks-dev` / `eu-central-1` |
| EKS | наявний `uav-dev-eks`, приватний API через VPN/NetBird |
| Namespace / Deployment / Service | `auth2` / `keycloak-auth2` / `keycloak-auth2` |
| URL | `https://auth2.kub.army`, без префікса `/auth` |
| Доступ | internet-facing ALB; публічний OIDC, `/admin` за source-IP allowlist; DNS only у Cloudflare |
| БД / роль | нова `keycloak_auth2` / `keycloak_auth2` на **dev writer RDS** |
| Realm | новий `kub-dev`; узгодити назву з командою застосунків |
| Keycloak / тема | `23.0.7` / `kub`, пакет `1.0.0` |
| Розмір | 1 replica, local cache, Recreate; без HA, з перервою при рестарті |
| Ресурси pod | стартово request 250m CPU / 768Mi; limit 1 CPU / 1536Mi |
| Зберігання | RDS для даних; без PVC/H2; тимчасовий кеш у emptyDir |

**Версійне обмеження.** 23.0.7 вийшла 22.02.2024. Фіксуємо її за вимогою,
але це старий реліз, а upstream виправляє безпеку в поточній або наступній
major.minor гілці. Обмеження доступу не замінює оновлень. Для цього dev
використовувати тестові облікові записи, зафіксувати результат сканування
образу та відповідального за перехід на підтримувану версію.
[Реліз](https://www.keycloak.org/2024/02/keycloak-2307-released),
[політика безпеки](https://github.com/keycloak/keycloak/security/policy).

Питання, які DevOps має закрити до виконання:

1. Перевірити фактичні account/EKS/RDS проти погодженого dev-середовища.
   Новий AWS account/EKS/RDS instance не створюється цим ранбуком; створюється
   нова логічна БД у наявному dev RDS.
2. Визначити стабільний **публічний egress CIDR** адміністративної мережі/VPN
   для `/admin`. Приватна VPN-адреса `10.x.x.x` не підходить для source-IP
   condition на internet-facing ALB. Перевірити доступ dev backend до
   публічних discovery/JWKS/token endpoints через NAT або узгоджений маршрут.
3. Узгодити realm, точні dev redirect URI, web origins, власників адмінки,
   SMTP (якщо потрібне відновлення пароля) та цільові RPO/RTO.

Якщо базової платформи ще немає, спочатку створити її окремою IaC-зміною:
dev VPC/private subnets → EKS/node groups/VPN → AWS Load Balancer Controller
та його IAM → private RDS → ECR → ACM/DNS. Вихідні стеки:
`terraform/envs/dev/{vpc,eks,rds,ecr}/` у `Beacons.Terraform`; звірити їхні
backend, provider account і план, не застосовувати всі стеки автоматично.
Після готовності платформи продовжити нижче. Версії EKS/controller/PG
узгоджуються окремо; версія Keycloak залишається 23.0.7.

## 2. Що взято з rel, а що виправлено

Це огляд **коду**, а не аудит поточного кластера. Шляхи в таблиці відносні
до `Beacons.Terraform`.

| Джерело | Спостереження | Рішення для auth2 |
|---|---|---|
| `terraform/envs/rel/CLAUDE.md:67`, `helm/keycloak/Chart.yaml:1` | Документ радить Bitnami chart, але в репозиторії власний chart; версія 23.0.0 | Використовувати офіційний образ 23.0.7 і наведені маніфести; не змішувати values Bitnami та власного chart |
| `terraform/envs/dev/CLAUDE.md:1` | Dev-документ містить rel account, prod RDS та rel ACM | STS, cluster ARN і RDS перевіряються до змін; каталог `dev` сам по собі не гарантує dev account |
| `helm/keycloak/values-dev.yaml:7` | Dev hostname теж `auth.kub.army` | Окремий `auth2.kub.army`, окремі namespace/БД/сертифікат |
| `helm/keycloak/templates/deployment.yaml:16` | Жорстко задано nodeSelector `role: b12` | Перевірений dev node pool; не переносити selector без перевірки місткості |
| `helm/keycloak/templates/deployment.yaml:22` | `start`, build-time health/metrics передано під час запуску | Збирати оптимізований образ у CI, запускати `start --optimized` |
| `helm/keycloak/templates/deployment.yaml:50` | Вимкнені hostname strict і strict HTTPS | Фіксований HTTPS URL, strict=true; proxy edge лише за довіреним ALB |
| `helm/keycloak/templates/deployment.yaml:63` | Обидві probes використовують `/realms/master`, немає startupProbe і resources | `/health/started`, `/health/ready`, `/health/live`, ресурси та securityContext |
| `helm/keycloak/templates/ingress.yaml:8` | Internet-facing `/`, без явного healthcheck-path | Явні публічні маршрути, `/admin` тільки за CIDR; healthcheck `/health/ready` напряму до pod |
| `helm/keycloak/templates/secret.yaml:7`, `terraform/envs/rel/CLAUDE.md:70` | Секрет із Helm values, документований спільний DB admin | Окрема роль БД; зовнішній Secret; без паролів у Git, Helm values/argv чи Terraform state |
| `helm/keycloak/templates/deployment.yaml:24` | Не задані параметри перевірки TLS до БД | JDBC `sslmode=verify-full` та RDS CA |
| `helm/keycloak/templates/servicemonitor.yaml:1` | ServiceMonitor створюється без перевірки наявності CRD | Додавати лише якщо Prometheus Operator встановлено |
| `terraform/envs/dev/rds/main.tf:62` | Є deletion protection, фінальний snapshot і 30 днів backup | Зберегти ці заходи; перевірити фактичні backups і відновлення |

Модуль `terraform/modules/rds/variables.tf:91` задає PostgreSQL 16.
У `keycloak/keycloak`, тег `23.0.7`, `pom.xml` задає тестову версію PostgreSQL
15. Це **не доказ несумісності з 16**, але й не підтвердження її: перевірити
перший старт, Liquibase, вхід та відновлення на фактичній версії dev RDS.
Якщо політика вимагає саме upstream-tested PG — виділити RDS PostgreSQL 15
з актуальним доступним minor, перевіреним у цільовому регіоні. Не знижувати
версію спільної dev-БД заради цього сервісу.

## 3. Перевірити account, доступ і залежності

Потрібні AWS CLI v2, kubectl, Docker з buildx, jq, Python 3, curl, openssl,
psql та GNU envsubst (`gettext`), VPN до dev VPC, права на EKS namespace,
dev ECR, ACM і DNS. Команди виконуються на робочій станції DevOps/у CI.
Не вмикати `set -x` у сесії із секретами.

```bash
set -euo pipefail
export KC_AWS_PROFILE=mayaks-dev
export KC_REGION=eu-central-1
export KC_ACCOUNT=546518615280
export KC_CLUSTER=uav-dev-eks
export KC_CONTEXT=keycloak-auth2-dev
export KC_KUBECONFIG="$(mktemp)"
chmod 600 "$KC_KUBECONFIG"

aws sso login --profile "$KC_AWS_PROFILE"
test "$(aws sts get-caller-identity --profile "$KC_AWS_PROFILE" \
  --query Account --output text)" = "$KC_ACCOUNT"
test "$(aws eks describe-cluster --name "$KC_CLUSTER" \
  --profile "$KC_AWS_PROFILE" --region "$KC_REGION" \
  --query cluster.arn --output text)" = \
  "arn:aws:eks:${KC_REGION}:${KC_ACCOUNT}:cluster/${KC_CLUSTER}"
aws eks update-kubeconfig --name "$KC_CLUSTER" --region "$KC_REGION" \
  --profile "$KC_AWS_PROFILE" --kubeconfig "$KC_KUBECONFIG" --alias "$KC_CONTEXT"
kdev() { kubectl --kubeconfig "$KC_KUBECONFIG" --context "$KC_CONTEXT" "$@"; }
kdev cluster-info
kdev get nodes -L role,kubernetes.io/arch
kdev -n kube-system get deployment aws-load-balancer-controller
kdev get ingressclass alb
kdev get namespace auth2 --ignore-not-found
```

Якщо namespace вже зайнятий — спочатку з'ясувати власника й наявні ресурси;
не перезаписувати їх. Ранбук розрахований на новий namespace. Не продовжувати,
якщо account або кластер відрізняється. Всі подальші `kdev` використовують
цей окремий kubeconfig, а не поточний контекст оператора.

Перевірити dev writer RDS (ідентифікатор нижче — з коду, звірити з AWS):

```bash
aws rds describe-db-instances --db-instance-identifier uav-dev-postgres \
  --profile "$KC_AWS_PROFILE" --region "$KC_REGION" \
  --query 'DBInstances[0].{Arn:DBInstanceArn,Host:Endpoint.Address,Engine:EngineVersion,Public:PubliclyAccessible,Encrypted:StorageEncrypted,BackupDays:BackupRetentionPeriod,Vpc:DBSubnetGroup.VpcId,ReplicaOf:ReadReplicaSourceDBInstanceIdentifier}'
```

Потрібні writer, правильний dev VPC, `Public=false`, шифрування й backups.
Скопіювати підтверджений endpoint у `KC_DB_HOST`; не використовувати rel
endpoint, read replica або довільний DNS alias (важливо для TLS hostname).
У Security Groups дозволити 5432 тільки від потрібних workload SG та
адміністративного VPN/bastion. Для pod 8080 дозволити трафік від ALB backend
SG, kubelet probes і внутрішнього моніторингу; не відкривати NodePort чи
публічний Service. Обмежити доступ інших workload через NetworkPolicy/SG
for Pods згідно з реально ввімкненим мережевим механізмом EKS. Сам об'єкт
NetworkPolicy без підтримки CNI не є захистом.

Для internet-facing ALB потрібні public subnets щонайменше у двох AZ,
Internet Gateway і теги для discovery або явні subnet IDs у Ingress.
EKS pods і RDS лишаються у private subnets; доступ до EKS API/БД — через VPN.
Не довіряти клієнтським `Forwarded`/`X-Forwarded-*`: перевірити їх обробку
довіреним proxy, заборонити обхід ALB і перевірити spoofed-header сценарій
при прийманні. `hostname-strict` сам не обмежує мережевий доступ.

## 4. Підготувати порожню БД та секрети

Працювати в окремому приватному каталозі **поза Git**. Надалі всі локальні
файли команд зберігаються в ньому, крім каталогу з готовим пакетом теми.

```bash
umask 077
mkdir -p "$HOME/keycloak-auth2-work"
cd "$HOME/keycloak-auth2-work"
export KC_DB_HOST='REPLACE_WITH_VERIFIED_DEV_RDS_WRITER_ENDPOINT'
curl --fail --show-error --location \
  https://truststore.pki.rds.amazonaws.com/eu-central-1/eu-central-1-bundle.pem \
  --output rds-ca.pem
openssl crl2pkcs7 -nocrl -certfile rds-ca.pem | openssl pkcs7 -print_certs -noout
sha256sum rds-ca.pem > rds-ca.pem.sha256
```

Сертифікати CA публічні; перевірити issuer/термін дії, зберегти їх checksum
з артефактом розгортання. Оновлення CA — окрема контрольована операція.
Підключитися через VPN до `postgres` як dev DBA із prompt пароля:

```bash
read -r -p 'Dev DBA username: ' KC_DBA_USER
psql "host=$KC_DB_HOST port=5432 dbname=postgres user=$KC_DBA_USER sslmode=verify-full sslrootcert=$PWD/rds-ca.pem" -W
```

У psql виконати **один раз**, не продовжувати після помилки:

```sql
\set ON_ERROR_STOP on
SELECT current_database(), current_user, version();
SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid();
CREATE ROLE keycloak_auth2 LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
\password keycloak_auth2
GRANT keycloak_auth2 TO CURRENT_USER;
CREATE DATABASE keycloak_auth2 OWNER keycloak_auth2 ENCODING 'UTF8' TEMPLATE template0;
REVOKE ALL ON DATABASE keycloak_auth2 FROM PUBLIC;
\connect keycloak_auth2
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO keycloak_auth2;
REVOKE keycloak_auth2 FROM CURRENT_USER;
\quit
```

Пароль згенерувати й зберегти в командному secret manager; `\password`
запитує його без запису відкритого пароля в SQL history. Роль володіє лише
своєю БД/схемою: Keycloak потрібен DDL для Liquibase, але не RDS admin.
Якщо роль/БД вже існує, зупинитися й перевірити походження; не виконувати DROP.
Перевірити підключення цією роллю з TLS і що БД ще порожня.

Створити namespace та два Kubernetes Secrets, якими не володіє Helm.
Базовий bootstrap нижче придатний і без External Secrets Operator.
Для регулярної експлуатації переважний уже прийнятий у команді механізм
синхронізації з AWS Secrets Manager через workload identity з доступом
лише до конкретних секретів. Не додавати паролі до Terraform resources.

```bash
kdev create namespace auth2
kdev -n auth2 create configmap keycloak-rds-ca --from-file=rds-ca.pem
read -r -s -p 'Password for DB role keycloak_auth2: ' KC_DB_PASSWORD
printf '\n'
printf '%s' "$KC_DB_PASSWORD" > db-password
unset KC_DB_PASSWORD
kdev -n auth2 create secret generic keycloak-auth2-db --from-file=db-password
read -r -s -p 'New initial Keycloak admin password (save in vault): ' KC_ADMIN_PASSWORD
printf '\n'
printf '%s' "$KC_ADMIN_PASSWORD" > admin-password
unset KC_ADMIN_PASSWORD
kdev -n auth2 create secret generic keycloak-auth2-bootstrap --from-file=admin-password
rm db-password admin-password
```

Не виводити Secrets у термінал/CI logs. Забезпечити RBAC на читання Secrets
та encryption at rest у кластері. Видалення тимчасових файлів не гарантує
їх фізичного стирання на SSD — використовувати зашифровану робочу станцію.

## 5. Звідки взяти контейнер і як додати тему

Офіційний upstream образ: **`quay.io/keycloak/keycloak:23.0.7`**.
[Quay](https://quay.io/repository/keycloak/keycloak),
[документація контейнера у тегу 23.0.7](https://github.com/keycloak/keycloak/blob/23.0.7/docs/guides/server/containers.adoc).
Не брати rel ECR tag `23.0.0`, `latest` чи Bitnami image для цього прикладу.
Digest не вигадувати: отримати з registry перед збіркою та записати в release.

```bash
docker buildx imagetools inspect quay.io/keycloak/keycloak:23.0.7
read -r -p 'Upstream manifest digest (sha256:...): ' KC_BASE_DIGEST
[[ "$KC_BASE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
export KC_BASE_IMAGE="quay.io/keycloak/keycloak:23.0.7@${KC_BASE_DIGEST}"
```

Скопіювати `kub-theme-1.0.0.jar`, `kub-theme-1.0.0.zip`, `SHA256SUMS` з
`custom-themes/dist/` у робочий каталог та виконати `sha256sum -c SHA256SUMS`.
Збірка самого пакета: `python3 custom-themes/build-package.py` з repo Keycloak.
Підготувати такий `Dockerfile` у робочому каталозі:

```dockerfile
ARG KC_BASE_IMAGE
FROM ${KC_BASE_IMAGE}
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_CACHE=local
COPY --chown=1000:0 kub-theme-1.0.0.jar /opt/keycloak/providers/kub-theme-1.0.0.jar
RUN /opt/keycloak/bin/kc.sh build
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start", "--optimized"]
```

`cache=local` тут — свідомий вибір для **одного dev pod**, це build-time
опція у 23.0.7. Не збільшувати replicas/HPA без окремої зміни на кластерний
Infinispan, discovery і перевірки failover. Онлайн-сесії можуть втрачатися
при рестарті. Кеш тем лишається ввімкненим.

ECR repository у **dev account**: `uav/keycloak-auth2`, immutable tags,
сканування образів, lifecycle policy зі збереженням попередніх релізів.
Перед збіркою створити `.dockerignore` у робочому каталозі:

```text
*
!Dockerfile
!kub-theme-1.0.0.jar
```

Секрети та kubeconfig не мають потрапити в build context. Створити ECR
репозиторій окремою IaC-зміною або, для першого ручного bootstrap:

```bash
aws ecr create-repository --repository-name uav/keycloak-auth2 \
  --image-tag-mutability IMMUTABLE --image-scanning-configuration scanOnPush=true \
  --profile "$KC_AWS_PROFILE" --region "$KC_REGION"
export KC_ECR="${KC_ACCOUNT}.dkr.ecr.${KC_REGION}.amazonaws.com"
export KC_IMAGE_TAG="${KC_ECR}/uav/keycloak-auth2:23.0.7-kub-1.0.0-r1"
aws ecr get-login-password --profile "$KC_AWS_PROFILE" --region "$KC_REGION" \
  | docker login --username AWS --password-stdin "$KC_ECR"
docker buildx build --platform linux/amd64 --build-arg KC_BASE_IMAGE="$KC_BASE_IMAGE" \
  --tag "$KC_IMAGE_TAG" --push .
export KC_IMAGE_DIGEST="$(aws ecr describe-images --repository-name uav/keycloak-auth2 \
  --image-ids imageTag=23.0.7-kub-1.0.0-r1 --profile "$KC_AWS_PROFILE" \
  --region "$KC_REGION" --query 'imageDetails[0].imageDigest' --output text)"
[[ "$KC_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
export KC_IMAGE="${KC_ECR}/uav/keycloak-auth2@${KC_IMAGE_DIGEST}"
```

Якщо ECR repository вже існує — перевірити його account/політики, пропустити
create. Для іншої архітектури змінити build platform та nodeSelector разом;
не покладатися на архітектуру ноутбука.
Зберегти звіт сканера (включно з Java-залежностями; basic ECR scan не замінює
повної перевірки), digest base/final image, checksum JAR, commit і Dockerfile.
Не видавати старий 23.0.7 за реліз без вразливостей. EKS node IAM має право
pull тільки потрібних ECR images; AWS credentials у pod Keycloak не потрібні.

## 6. Розгорнути Keycloak без зовнішнього маршруту

Зберегти як `keycloak.yaml.in` у робочому каталозі:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: keycloak-auth2
  namespace: auth2
automountServiceAccountToken: false
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: keycloak-auth2
  namespace: auth2
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: keycloak-auth2
  template:
    metadata:
      labels:
        app: keycloak-auth2
    spec:
      serviceAccountName: keycloak-auth2
      automountServiceAccountToken: false
      terminationGracePeriodSeconds: 60
      nodeSelector:
        role: kub
        kubernetes.io/arch: amd64
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 0
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: keycloak
          image: ${KC_IMAGE}
          imagePullPolicy: IfNotPresent
          args: ["start", "--optimized"]
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          env:
            - name: KC_DB_URL
              value: "jdbc:postgresql://${KC_DB_HOST}:5432/keycloak_auth2?sslmode=verify-full&sslrootcert=/opt/keycloak/conf/rds/rds-ca.pem"
            - name: KC_DB_USERNAME
              value: keycloak_auth2
            - name: KC_DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: keycloak-auth2-db
                  key: db-password
            - name: KEYCLOAK_ADMIN
              value: bootstrap-auth2
            - name: KEYCLOAK_ADMIN_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: keycloak-auth2-bootstrap
                  key: admin-password
            - name: KC_PROXY
              value: edge
            - name: KC_HOSTNAME_URL
              value: https://auth2.kub.army
            - name: KC_HOSTNAME_STRICT
              value: "true"
            - name: KC_HOSTNAME_STRICT_HTTPS
              value: "true"
            - name: KC_HOSTNAME_STRICT_BACKCHANNEL
              value: "true"
            - name: KC_DB_POOL_INITIAL_SIZE
              value: "5"
            - name: KC_DB_POOL_MIN_SIZE
              value: "5"
            - name: KC_DB_POOL_MAX_SIZE
              value: "20"
          ports:
            - name: http
              containerPort: 8080
          resources:
            requests:
              cpu: 250m
              memory: 768Mi
            limits:
              cpu: "1"
              memory: 1536Mi
          startupProbe:
            httpGet:
              path: /health/started
              port: http
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 60
          readinessProbe:
            httpGet:
              path: /health/ready
              port: http
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          livenessProbe:
            httpGet:
              path: /health/live
              port: http
            periodSeconds: 20
            timeoutSeconds: 5
            failureThreshold: 3
          volumeMounts:
            - name: data
              mountPath: /opt/keycloak/data
            - name: tmp
              mountPath: /tmp
            - name: rds-ca
              mountPath: /opt/keycloak/conf/rds
              readOnly: true
      volumes:
        - name: data
          emptyDir:
            sizeLimit: 256Mi
        - name: tmp
          emptyDir:
            sizeLimit: 256Mi
        - name: rds-ca
          configMap:
            name: keycloak-rds-ca
---
apiVersion: v1
kind: Service
metadata:
  name: keycloak-auth2
  namespace: auth2
  labels:
    app: keycloak-auth2
spec:
  type: ClusterIP
  selector:
    app: keycloak-auth2
  ports:
    - name: http
      port: 80
      targetPort: http
---
apiVersion: v1
kind: Service
metadata:
  name: keycloak-auth2-admin
  namespace: auth2
spec:
  type: ClusterIP
  selector:
    app: keycloak-auth2
  ports:
    - name: http
      port: 80
      targetPort: http
```

Другий Service веде до того самого pod, але дозволяє задати окрему
ALB source-IP condition **лише** для адміністративного маршруту. Не
переносити цю condition на основний Service: це закриє і публічний вхід.

`role: kub` — базовий dev pool із коду; перевірити його на кроці 3.
UID 1000/GID 0 відповідає офіційному контейнеру; процес не root. Валідувати
сумісність із Pod Security політикою кластера. Heap у 23.0.7 за замовчуванням
512Mi: не переносити автоматично сучасні поради про процент RAM для JVM.

```bash
: "${KC_IMAGE:?Set verified image digest}"
: "${KC_DB_HOST:?Set verified dev writer endpoint}"
envsubst '${KC_IMAGE} ${KC_DB_HOST}' < keycloak.yaml.in > keycloak.yaml
kdev apply --dry-run=server -f keycloak.yaml
kdev diff -f keycloak.yaml  # exit 1 означає наявність різниці; переглянути її
# Після перегляду різниці виконати окремо:
kdev apply -f keycloak.yaml
kdev -n auth2 rollout status deployment/keycloak-auth2 --timeout=10m
kdev -n auth2 logs deployment/keycloak-auth2 --tail=100
```

При `set -e` команда diff із кодом 1 завершує скрипт; це навмисна точка
перегляду. Не обгортати весь ранбук у один автоматичний shell script.
Перший старт створює схему Liquibase; не переривати його довільним рестартом.
Health/metrics у **23.0.7** знаходяться на application port 8080, не на 9000.
Метрики ввімкнені також для DB readiness check. Для перевірки з іншого
термінала з тим самим kubeconfig:

```bash
kdev -n auth2 port-forward service/keycloak-auth2 18080:80 --address=127.0.0.1
```

У першому терміналі: `curl -fsS http://127.0.0.1:18080/health/ready`.
Очікується `UP`, у checks — перевірка з'єднань БД. Цей port-forward призначений
для health, не змінює канонічний HTTPS hostname для браузерного входу.

## 7. TLS, ALB і DNS

У ACM **dev account / eu-central-1** запросити public certificate для
`auth2.kub.army`, validation DNS. Створити виданий ACM validation CNAME у
Cloudflare як DNS only, дочекатися `ISSUED`, зберегти validation record
для автоматичного renewal. Можна використати наявний сертифікат лише після
перевірки SAN, account, регіону й статусу. Не переносити rel ARN.

```bash
export KC_CERT_ARN='REPLACE_WITH_DEV_ACM_CERTIFICATE_ARN'
aws acm describe-certificate --certificate-arn "$KC_CERT_ARN" \
  --profile "$KC_AWS_PROFILE" --region "$KC_REGION" \
  --query 'Certificate.{Status:Status,SANs:SubjectAlternativeNames,Expires:NotAfter}'
export KC_ADMIN_CIDR='REPLACE_WITH_ADMIN_PUBLIC_EGRESS_IPV4_CIDR'
```

Для `KC_ADMIN_CIDR` використати зовнішню адресу після VPN/SNAT, наприклад
погоджений статичний `/32`. Не задавати для адмінки `0.0.0.0/0`. Якщо VPN
має split tunnel, доступ браузера до цього hostname повинен виходити через
погоджений VPN egress. Без стабільного egress спочатку організувати його
або окремий приватний адміністративний маршрут.
Зберегти як `ingress.yaml.in`:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: keycloak-auth2
  namespace: auth2
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/ip-address-type: ipv4
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
    alb.ingress.kubernetes.io/certificate-arn: ${KC_CERT_ARN}
    alb.ingress.kubernetes.io/inbound-cidrs: 0.0.0.0/0
    alb.ingress.kubernetes.io/conditions.keycloak-auth2-admin: >-
      [{"field":"source-ip","sourceIpConfig":{"values":["${KC_ADMIN_CIDR}"]}}]
    alb.ingress.kubernetes.io/ssl-policy: ELBSecurityPolicy-TLS13-1-2-2021-06
    alb.ingress.kubernetes.io/backend-protocol: HTTP
    alb.ingress.kubernetes.io/healthcheck-path: /health/ready
    alb.ingress.kubernetes.io/healthcheck-port: traffic-port
    alb.ingress.kubernetes.io/success-codes: "200"
spec:
  ingressClassName: alb
  rules:
    - host: auth2.kub.army
      http:
        paths:
          - path: /realms
            pathType: Prefix
            backend:
              service:
                name: keycloak-auth2
                port:
                  name: http
          - path: /resources
            pathType: Prefix
            backend:
              service:
                name: keycloak-auth2
                port:
                  name: http
          - path: /js
            pathType: Prefix
            backend:
              service:
                name: keycloak-auth2
                port:
                  name: http
          - path: /robots.txt
            pathType: Exact
            backend:
              service:
                name: keycloak-auth2
                port:
                  name: http
          - path: /admin
            pathType: Prefix
            backend:
              service:
                name: keycloak-auth2-admin
                port:
                  name: http
```

`/admin` тут доступний лише із `KC_ADMIN_CIDR`: ALB перевіряє source IP
мережевого з'єднання, а не клієнтський `X-Forwarded-For`. За відсутності
збігу запит має потрапити в стандартну fixed 404 відповідь ALB. `/`,
`/metrics`, `/health` не маршрутизуються через Ingress; healthcheck ALB
звертається до pod напряму. Порт 80 не слухається, використовувати HTTPS.
Для зв'язку ALB → pod HTTP допустимий лише в ізольованій довіреній мережі;
якщо потрібне шифрування цього сегмента — окремо налаштувати TLS у pod,
`KC_PROXY=reencrypt`, backend HTTPS і probes/сертифікати, не міняти тільки
одну анотацію. Не додавати Ingress до спільної rel IngressGroup.

```bash
[[ "$KC_CERT_ARN" == "arn:aws:acm:${KC_REGION}:${KC_ACCOUNT}:certificate/"* ]]
python3 - <<'PY'
import ipaddress, os
network = ipaddress.ip_network(os.environ['KC_ADMIN_CIDR'], strict=True)
assert network.version == 4 and network.prefixlen > 0 and network.is_global, \
    'Use the approved public IPv4 administrative egress CIDR'
PY
envsubst '${KC_CERT_ARN} ${KC_ADMIN_CIDR}' < ingress.yaml.in > ingress.yaml
kdev apply --dry-run=server -f ingress.yaml
kdev diff -f ingress.yaml
# Після перегляду різниці виконати окремо:
kdev apply -f ingress.yaml
kdev -n auth2 get ingress keycloak-auth2 -w
```

Коли ALB готовий і target healthy, отримати його hostname:

```bash
kdev -n auth2 get ingress keycloak-auth2 \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

У Cloudflare zone `kub.army` створити **CNAME `auth2` → отриманий ALB hostname**,
DNS only, TTL Auto. ALB резолвиться в публічні адреси; перевірити вихід dev
бекендів до нього. Перед першим входом в адмінку перевірити listener rule:
host + `/admin` path + source-ip condition, backend `keycloak-auth2-admin`;
не повинно бути іншого правила `/` або `/admin` без цієї умови. Перевірити
і `/admin`, і `/admin/`, і `/admin/master/console/` з дозволеної та сторонньої
мережі; з останньої очікується 404. Публічний `/realms/master` лишається
доступним для login flow, тому для admin accounts потрібні сильні паролі,
MFA і brute-force protection також у `master`.
Не чіпати запис `auth` і не вказувати IP окремої ALB-ноди.

## 8. Додатковий захист і Cloudflare Proxy

Основний приклад уже реалізує погоджену модель публічного входу та
обмеженої адмінки. Для публічного старого релізу додатково налаштувати AWS
WAF на ALB: керовані правила та погоджені rate limits, спочатку перевірити
login/token/refresh flows, щоб правила не блокували легітимних користувачів.
WAF ARN приєднується через `alb.ingress.kubernetes.io/wafv2-acl-arn` після
створення відповідного dev Web ACL. Альтернатива для адміністративного
доступу — окремий private admin hostname із internal ALB. Зміна
`KC_HOSTNAME_ADMIN_URL` задає URL, але сама по собі не закриває admin API.
Перевірити, що адміністративні маршрути неможливо обійти через public host
чи hostname самого ALB. Не публікувати health/metrics.

**Не вмикати Cloudflare Proxied для базового прикладу без переробки правил
доступу.** Якщо цей варіант буде потрібен: Full (strict), чинний ACM certificate на
origin, bypass cache для всього auth hostname, закрити прямий доступ до
origin відповідним механізмом. Source-IP conditions ALB тоді бачать
Cloudflare IP, а не IP користувача: простий VPN allowlist на ALB не працює
як раніше. Визначити довірений ланцюжок client IP і захист адмінки до
відкриття доступу. WAF/IP-фільтри не вважати виправленням старої версії.

## 9. Перший вхід, realm і тема

1. З дозволеного адміністративного egress відкрити `https://auth2.kub.army/admin/`; увійти як
   `bootstrap-auth2` з паролем із vault. Переконатися, що це новий `master`.
2. Створити іменних адміністраторів, увімкнути для них MFA; перевірити вхід
   в окремій приватній сесії. Зберегти контрольований emergency-access
   обліковий запис відповідно до політики команди.
3. Створити realm `kub-dev`. `master` використовувати для адміністрування,
   не для прикладних користувачів. Встановити Require SSL = all requests,
   вимкнути самореєстрацію, якщо вона не потрібна; налаштувати brute-force
   protection, політику паролів, сесій, user/admin events та строки retention.
4. Realm settings → Themes → Login theme = `kub`; Localization → `uk` як
   supported/default locale. За бажанням вибрати цю login theme і в `master`.
   Перевірити відсутність client-level override `login_theme` на іншу тему.
5. Створити **нові dev clients** із точними redirect URI та web origins.
   Для SPA — public client, Authorization Code + PKCE S256; секрет у браузер
   не видається. Для backend/service clients — окремі секрети й мінімальні
   service-account roles. Не вмикати implicit/password grant без вимоги
   сумісності, не ставити глобальний wildcard `*`.
6. Узгодити issuer у dev UI/API:
   `https://auth2.kub.army/realms/kub-dev`. Redirect URI — адреса повернення
   **застосунку**, а не механічна заміна hostname Keycloak. Перевірити audience,
   roles/mappers та logout URI. Rel-конфігурацію застосунків не змінювати.
7. Якщо потрібен reset password — налаштувати dev SMTP із TLS і тестовими
   адресатами та дозволити відповідний egress; інакше reset вимкнений.
8. Після перевірки іменних адмінів прибрати з `keycloak.yaml.in` і rendered
   `keycloak.yaml` дві env-змінні `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`,
   застосувати оновлений manifest і дочекатися Ready. Потім видалити
   `keycloak-auth2-bootstrap` Secret та початковий account `bootstrap-auth2`.
   Саме видалення env/Secret **не видаляє адміністратора з БД**. У 23.0.7 ці
   env створюють лише початкового адміна; зміна Secret не скидає існуючий пароль.

У 23.0.7 використовуються `KEYCLOAK_ADMIN*`, hostname v1 та `KC_PROXY=edge`.
Не підставляти з документації нових версій `KC_BOOTSTRAP_ADMIN_*`,
`KC_PROXY_HEADERS` або management port 9000.

## 10. Приймання та спостереження

```bash
curl --fail --show-error --silent \
  https://auth2.kub.army/realms/kub-dev/.well-known/openid-configuration \
  | jq -e '.issuer == "https://auth2.kub.army/realms/kub-dev"'
kdev -n auth2 get pods -l app=keycloak-auth2
kdev -n auth2 get deployment keycloak-auth2 \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
```

Не використовувати `curl -k` чи вимикання TLS як критерій успіху.
Перед передачею середовища перевірити:

- Сертифікат, discovery, JWKS та token endpoint працюють через канонічний
  HTTPS hostname з браузера **і dev backend**; немає HTTP/localhost/rel URL
  у metadata чи редиректах. Не зберігати access/refresh tokens у звіті.
- Успішний вхід, неправильний пароль, logout, оновлення токена й відмова
  для несанкціонованого redirect URI; MFA та reset, якщо ввімкнені.
- Тема `kub`: «Вхід до системи», «Логін», українські помилки, лого й шрифти
  повертають 200; картка поміщається на desktop/mobile. Немає запитів до CDN.
- Із сторонньої мережі публічний вхід працює, а `/admin` отримує 404 навіть
  з підробленим `X-Forwarded-For` дозволеної адреси. `/metrics`, `/health` через
  Ingress не повертають внутрішні дані; `/admin` закритий згідно з моделлю
  доступу. Підроблені proxy headers не змінюють issuer чи схему URL.
- RDS підключення мають `ssl=true` у `pg_stat_ssl`, runtime role не DBA.
  Міграція завершена, немає OOM/restart loop; фактичний imageID відповідає
  підготовленому digest (для multiarch це може бути digest конкретної платформи).
- Контрольований рестарт pod зберігає realm/users/clients у БД; повторний
  вхід може знадобитися — для цього single-pod dev це очікувано.
- Backup/PITR існує і виконано тест відновлення в окремий target, див. нижче.

Метрики `/metrics` збирати тільки через ClusterIP з namespace моніторингу.
Якщо встановлений Prometheus Operator — додати ServiceMonitor із selector
`app: keycloak-auth2`, namespace `auth2`, endpoint port `http`, path `/metrics`;
його labels узгодити з реальним selector Prometheus. Без CRD ServiceMonitor
не застосовувати. Спостерігати Ready=0, рестарти/OOM, ALB 5xx/latency,
CPU/RAM, RDS connections/storage, невдалі входи, термін TLS certificate і
свіжість backups. Доступ до логів обмежити, debug/token logging не вмикати.

## 11. Backup, оновлення та відкат

Початкові цілі для узгодження: RPO ≤ 15 хв за PITR, RTO ≤ 2 год після
перевірки restore; це цілі, не виміряні гарантії. Перевірити фактичний
LatestRestorableTime та retention RDS. Зберегти deletion protection,
фінальний snapshot; для наявного dev RDS не зменшувати задані 30 днів backup.
Realm export не замінює backup БД; він може містити секрети й не підходить
для Git. Перед версійним оновленням — ручний snapshot і збережений старий image.

Тест відновлення / аварійне відновлення:

1. Вибрати snapshot/PITR point, зафіксувати час і поточні image/theme digests.
2. Відновити RDS **в новий dev instance**, у private subnets із потрібним SG
   та шифруванням. Для shared RDS snapshot містить усі БД: не перемикати на
   нього інші dev застосунки. При необхідності DBA переносить лише БД
   `keycloak_auth2` із відновленого instance в новий ізольований target.
3. Перевірити DB role/password і endpoint з TLS. Запустити той самий image
   в ізольованому restore namespace; вимкнути SMTP, зовнішні IdP/webhooks,
   не підключати його до робочих клієнтів. Для нового тестового hostname
   підготувати окремі TLS/DNS/hostname настройки.
4. Перевірити realm, clients, тестовий вхід і тему; записати виміряні RPO/RTO.
5. При реальній аварії зупинити старий auth2 writer pod, щоб уникнути двох
   незалежних серверів на різних копіях БД з одним issuer. Оновити endpoint
   у manifest, застосувати, дочекатися Ready та повторити приймання.
   Не видаляти старий instance до завершення перевірки.

**Тільки зміна теми:** новий image tag/digest, `kc.sh build` уже виконаний
у Dockerfile; оновити image у manifest, dry-run/diff/apply. Rollback —
попередній image digest при тій самій версії сервера. Дані БД не відновлювати
без потреби. Зберігати попередні артефакти в ECR, не перезаписувати immutable tag.

**Зміна версії Keycloak:** прочитати migration guide, перевірити тему/FTL,
виконати upgrade на копії БД. Після міграції схеми старий image може бути
несумісний: `rollout undo` не є відкатом БД. План повернення включає
відновлення pre-upgrade snapshot у новий target і попередній image.

Ротація DB Secret: узгодити пароль ролі в PostgreSQL і secret manager,
оновити Kubernetes Secret, перезапустити Deployment, перевірити readiness;
env із Secret не оновлюється в уже запущеному процесі. Для одного pod
запланувати коротку перерву. Очищення dev не починати з видалення БД чи
namespace: спочатку прибрати клієнтські залежності, зберегти snapshot і
окремо погодити видалення даних.

## 12. Типові збої

| Симптом | Перевірка / дія |
|---|---|
| Pod Pending | selector/taints, вільні CPU/RAM dev pool; не переносити rel selector навмання |
| ImagePullBackOff | ECR account/digest/архітектура, node IAM, NAT або ECR/S3 VPC endpoints |
| Readiness DOWN | DB endpoint/SG/TLS CA/password, DB connections; не замінювати readiness перевіркою `/` |
| Permission denied при старті | UID/fsGroup та writable data/tmp volumes; не вимикати весь securityContext |
| Failed to start після `--optimized` | Чи збіглися build-time DB/cache/health/metrics, чи додано JAR до build |
| ALB 503/targets unhealthy | readiness, target port 8080, healthcheck `/health/ready`, backend SG, pod IP routing |
| Публічний вхід працює, `/admin` повертає 404 | Публічний source після VPN/SNAT, split tunnel, listener condition, Cloudflare DNS only |
| DNS працює, браузер timeout | ALB public subnets/IGW, SG, DNS, backend NAT/маршрут до ALB |
| HTTP redirect/mixed content | hostname v1 URL, proxy headers, realm Frontend URL та старі client settings |
| Тема відсутня / assets 404 | JAR у providers до build, metadata й directory entries, активна realm/client theme; див. DEVOPS.md |
| Адмін-пароль із Secret не працює | Initial admin уже існує; env не є механізмом reset пароля |

## 13. Що передати після розгортання

У командний deployment record: account/cluster/namespace, URL/realm,
image і base digests, checksum JAR/CA, commit manifests, DB identifier і
engine version, ACM ARN, модель доступу, посилання на vault (без значень),
результати перевірок/сканування/restore, відповідальні та план оновлення.
Перенести Dockerfile й несекретні manifests в окремий dev stack/CI GitOps
репозиторію інфраструктури з review; визначити одного власника ресурсів.
Не керувати тими самими об'єктами одночасно через ручний kubectl і Helm/Terraform.
Після завершення видалити тимчасовий kubeconfig: `rm "$KC_KUBECONFIG"`.

## Джерела й сумісність

- [Keycloak 23.0.7: containers](https://github.com/keycloak/keycloak/blob/23.0.7/docs/guides/server/containers.adoc),
  [hostname v1](https://github.com/keycloak/keycloak/blob/23.0.7/docs/guides/server/hostname.adoc),
  [reverse proxy і маршрути](https://github.com/keycloak/keycloak/blob/23.0.7/docs/guides/server/reverseproxy.adoc),
  [health](https://github.com/keycloak/keycloak/blob/23.0.7/docs/guides/server/health.adoc),
  [БД](https://github.com/keycloak/keycloak/blob/23.0.7/docs/guides/server/db.adoc),
  [версії залежностей](https://github.com/keycloak/keycloak/blob/23.0.7/pom.xml).
- [AWS Load Balancer Controller: annotations](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/)
  — звірити підтримку анотацій із встановленою версією controller.
- [AWS RDS PostgreSQL TLS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html),
  [RDS CA](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html).

Синтаксис Keycloak звірено з вихідним кодом тегу 23.0.7. AWS resources,
Docker image build і Kubernetes manifests потребують перевірки DevOps у
цільовому середовищі; успішне розгортання цим документом не заявляється.
