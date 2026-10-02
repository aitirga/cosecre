<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api, ApiError } from '../api/client'
import type { MigrationReport } from '../api/types'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ legacyTabs: string[]; registryTab: string }>()
const queryClient = useQueryClient()

/** Cheap progress, polled while the models re-read migrated documents. */
const statusQuery = useQuery({
  queryKey: ['migration-status'],
  queryFn: api.migrationStatus,
  refetchInterval: (query) =>
    query.state.data?.enrichment_running || query.state.data?.drive_running ? 3000 : false,
})

const preview = ref<MigrationReport | null>(null)
const error = ref('')

function report(e: unknown) {
  error.value = e instanceof ApiError ? e.message : 'Alguna cosa ha fallat. Torna-ho a provar.'
}

const previewMutation = useMutation({
  mutationFn: api.previewMigration,
  onSuccess: (data) => {
    preview.value = data
    error.value = ''
  },
  onError: report,
})

const runMutation = useMutation({
  mutationFn: api.runMigration,
  onSuccess: (data) => {
    preview.value = data
    error.value = ''
    queryClient.setQueryData(['migration-status'], data)
    void queryClient.invalidateQueries({ queryKey: ['documents'] })
  },
  onError: report,
})

const resumeMutation = useMutation({
  mutationFn: api.resumeEnrichment,
  onSuccess: (data) => queryClient.setQueryData(['migration-status'], data),
  onError: report,
})

const driveMutation = useMutation({
  mutationFn: api.uploadOriginalsToDrive,
  onSuccess: (data) => queryClient.setQueryData(['migration-status'], data),
  onError: report,
})

const status = computed(() => statusQuery.data.value)
const enrichTotal = computed(() =>
  status.value ? status.value.enrichment_done + status.value.enrichment_pending : 0,
)
const enrichPercent = computed(() =>
  enrichTotal.value ? Math.round((100 * (status.value?.enrichment_done ?? 0)) / enrichTotal.value) : 0,
)

const confirming = ref(false)

// Re-read the register once the models finish, so new fields show up.
watch(
  () => status.value?.enrichment_running,
  (running, before) => {
    if (before && !running) void queryClient.invalidateQueries({ queryKey: ['documents'] })
  },
)

onUnmounted(() => (preview.value = null))
</script>

<template>
  <section class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">Migració de les pestanyes antigues</h2>
        <p class="hint">
          Copia «{{ props.legacyTabs.join('» i «') }}» a «{{ props.registryTab }}». Les pestanyes
          antigues no s'esborren; només s'hi anota la referència a les files que no en tenien.
        </p>
      </div>
      <span v-if="status?.completed_at" class="badge badge-olive">
        <AppIcon name="check" :size="12" />
        Feta el {{ new Date(status.completed_at).toLocaleDateString('ca-ES') }}
      </span>
    </div>

    <div class="card-body body">
      <ol class="steps">
        <li>
          <strong>Previsualitza.</strong> Llegeix el full i diu què es copiaria, sense escriure res.
        </li>
        <li>
          <strong>Migra.</strong> Crea les entrades al registre, conservant tots els valors i les
          validacions.
        </li>
        <li>
          <strong>Completa amb IA.</strong> Els documents amb original (al servidor o a Drive) es
          tornen a llegir per omplir els camps nous: tipus, pagament, compte… Només s'omplen buits;
          res del que ja hi era es canvia.
        </li>
      </ol>

      <div class="actions">
        <button
          class="btn btn-outline"
          type="button"
          :disabled="previewMutation.isPending.value"
          @click="previewMutation.mutate()"
        >
          <AppIcon name="refresh" :class="{ spin: previewMutation.isPending.value }" />
          Previsualitza
        </button>
        <button
          class="btn btn-primary"
          type="button"
          :disabled="!preview || !preview.dry_run || !preview.to_create || runMutation.isPending.value"
          @click="confirming = true"
        >
          {{ runMutation.isPending.value ? 'Migrant…' : 'Migra' }}
        </button>
        <button
          v-if="status && status.enrichment_pending && !status.enrichment_running"
          class="btn btn-ghost"
          type="button"
          :disabled="resumeMutation.isPending.value"
          @click="resumeMutation.mutate()"
        >
          <AppIcon name="sparkles" />
          Reprèn la lectura amb IA ({{ status.enrichment_pending }})
        </button>
      </div>

      <dl v-if="preview" class="figures">
        <template v-for="(count, tab) in preview.tabs" :key="tab">
          <dt>Files a «{{ tab }}»</dt>
          <dd>{{ count }}</dd>
        </template>
        <dt>Ja migrades</dt>
        <dd>{{ preview.already_migrated }}</dd>
        <dt>{{ preview.dry_run ? 'Es crearan' : 'Creades' }}</dt>
        <dd>
          <strong>{{ preview.dry_run ? preview.to_create : preview.created }}</strong>
        </dd>
        <template v-if="preview.from_database">
          <dt>Recuperats de la base de dades</dt>
          <dd>{{ preview.from_database }}</dd>
        </template>
        <dt>Referències noves</dt>
        <dd>{{ preview.references_generated }}</dd>
        <dt>Amb original per rellegir</dt>
        <dd>{{ preview.with_file }}</dd>
      </dl>

      <div v-if="status && enrichTotal" class="enrich">
        <div class="enrich-top">
          <span>
            <AppIcon name="sparkles" :size="13" />
            Lectura amb IA: {{ status.enrichment_done }} de {{ enrichTotal }}
          </span>
          <span v-if="status.enrichment_running" class="badge badge-accent">
            <span class="badge-dot badge-dot-pulse" />
            En curs
          </span>
        </div>
        <div class="progress"><span :style="{ width: `${enrichPercent}%` }" /></div>
      </div>

      <div v-if="status && status.drive_configured && (status.drive_missing || status.drive_running)" class="drive">
        <span>
          <AppIcon name="image" :size="13" />
          {{ status.drive_missing }} originals només són al servidor i encara no a la carpeta de Drive.
        </span>
        <button
          class="btn btn-outline btn-sm"
          type="button"
          :disabled="status.drive_running || driveMutation.isPending.value"
          @click="driveMutation.mutate()"
        >
          {{ status.drive_running ? 'Pujant…' : 'Puja’ls a Drive' }}
        </button>
      </div>

      <details v-if="preview?.issues.length" class="issues">
        <summary>{{ preview.issues.length }} avisos</summary>
        <ul>
          <li v-for="(issue, index) in preview.issues" :key="index">
            <span class="mono muted">{{ issue.tab }}{{ issue.row ? ` · fila ${issue.row}` : '' }}</span>
            {{ issue.message }}
          </li>
        </ul>
      </details>

      <p v-if="error" class="notice notice-error">
        <AppIcon name="alert" :size="15" />
        <span>{{ error }}</span>
      </p>
    </div>

    <Teleport to="body">
      <div v-if="confirming && preview" class="overlay" @click.self="confirming = false">
        <div class="dialog" role="dialog" aria-modal="true">
          <h2 class="dialog-title">Migrar {{ preview.to_create }} documents?</h2>
          <p class="subtle">
            S'afegiran a «{{ props.registryTab }}» i a la base de dades. Abans de començar es fa una
            còpia de seguretat, i les pestanyes antigues es queden com estan.
          </p>
          <div class="dialog-actions">
            <button class="btn btn-outline" type="button" @click="confirming = false">
              Cancel·la
            </button>
            <button
              class="btn btn-primary"
              type="button"
              @click="
                () => {
                  confirming = false
                  runMutation.mutate()
                }
              "
            >
              Migra
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.body {
  display: grid;
  gap: 12px;
}

.steps {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 4px;
  font-size: var(--text-base);
  color: var(--ink-500);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.figures {
  display: grid;
  grid-template-columns: auto auto;
  justify-content: start;
  gap: 4px 18px;
  margin: 0;
  font-size: var(--text-base);
  font-variant-numeric: tabular-nums;
}

.figures dt {
  color: var(--ink-400);
}

.figures dd {
  margin: 0;
}

.enrich {
  display: grid;
  gap: 6px;
}

.enrich-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-base);
}

.enrich-top span:first-child {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.drive {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-1);
  font-size: var(--text-base);
}

.drive span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.issues summary {
  cursor: pointer;
  font-size: var(--text-base);
  color: var(--gold-800);
}

.issues ul {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: var(--text-sm);
  display: grid;
  gap: 2px;
}
</style>
