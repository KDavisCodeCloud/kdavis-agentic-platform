'use client'

/*
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 */

import { useState, useEffect, type ComponentType } from 'react'
import {
  Terminal,
  Code2,
  Plug,
  Copy,
  Check,
  RefreshCw,
  AlertTriangle,
  Plus,
  Key,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  listMCPKeys,
  generateMCPKey,
  revokeMCPKey,
  revokeAllMCPKeys,
  getMCPStatus,
  testMCPConnection,
  type MCPApiKey,
  type MCPConnectionStatus,
} from '@/lib/api'

const MCP_ENDPOINT =
  process.env.NEXT_PUBLIC_MCP_URL ?? 'https://mcp.theclouddecoded.com/mcp'
const OAUTH_AUTH_URL =
  process.env.NEXT_PUBLIC_OAUTH_AUTH_URL ??
  'https://api.theclouddecoded.com/auth/authorize'

type FlowId = 'claude_code' | 'embed' | 'direct'
type EmbedSubTab = 'mcp_sdk' | 'rest'
type IconComponent = ComponentType<{ className?: string }>

// ── CopyButton ────────────────────────────────────────────────────────────────

function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button
      onClick={copy}
      className={cn(
        'flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-200 transition-colors',
        className,
      )}
    >
      {copied ? <Check className="h-3 w-3 text-green-400" /> : <Copy className="h-3 w-3" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

// ── CodeBlock ─────────────────────────────────────────────────────────────────

function CodeBlock({ code, label }: { code: string; label?: string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-zinc-800">
        <span className="text-[10px] text-zinc-600 font-mono">{label ?? 'code'}</span>
        <CopyButton text={code} />
      </div>
      <pre className="p-3 text-xs font-mono text-zinc-300 overflow-x-auto leading-5 whitespace-pre">
        <code>{code}</code>
      </pre>
    </div>
  )
}

// ── StatusBar (polling active — Stop 5) ──────────────────────────────────────

function StatusBar({
  status,
  onRevokeAll,
}: {
  status: MCPConnectionStatus | null
  onRevokeAll: () => Promise<void>
}) {
  const [revokeConfirm, setRevokeConfirm] = useState(false)
  const [revoking, setRevoking]           = useState(false)

  const revokeButton = !revokeConfirm ? (
    <button
      className="ml-auto text-[10px] text-zinc-700 hover:text-red-400 transition-colors flex-shrink-0"
      onClick={() => setRevokeConfirm(true)}
    >
      Revoke all
    </button>
  ) : (
    <div className="ml-auto flex items-center gap-1.5 text-[10px] flex-shrink-0">
      <span className="text-red-400">Revoke all?</span>
      <button
        className="text-red-400 hover:text-red-300 font-medium disabled:opacity-40"
        disabled={revoking}
        onClick={async () => {
          setRevoking(true)
          await onRevokeAll()
          setRevoking(false)
          setRevokeConfirm(false)
        }}
      >
        Yes
      </button>
      <span className="text-zinc-700">/</span>
      <button className="text-zinc-500 hover:text-zinc-300" onClick={() => setRevokeConfirm(false)}>
        No
      </button>
    </div>
  )

  if (!status || !status.last_seen_at) {
    return (
      <div className="mb-5 flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-900/50 px-4 py-2.5 text-xs text-zinc-500">
        <span className="h-1.5 w-1.5 rounded-full bg-zinc-700 flex-shrink-0 animate-pulse" />
        <span>No connections yet — telemetry appears here after your first MCP call.</span>
        {revokeButton}
      </div>
    )
  }

  const topTools = Object.entries(status.tool_call_counts)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)

  return (
    <div className="mb-5 flex flex-wrap items-center gap-4 rounded-md border border-zinc-800 bg-zinc-900/50 px-4 py-2.5 text-xs">
      <div className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse flex-shrink-0" />
        <span className="font-medium text-zinc-200">{status.active_connections} active</span>
      </div>
      <span className="text-zinc-700">|</span>
      <span className="text-zinc-500">
        Last seen {new Date(status.last_seen_at).toLocaleString()}
      </span>
      <span className="text-zinc-700">|</span>
      <span className="text-zinc-500">{status.total_calls} total calls</span>
      {topTools.length > 0 && (
        <>
          <span className="text-zinc-700">|</span>
          <span className="font-mono text-zinc-600">
            {topTools.map(([name, count]) => `${name}×${count}`).join('  ')}
          </span>
        </>
      )}
      <span className="flex items-center gap-1 text-[10px] text-zinc-700">
        <RefreshCw className="h-2.5 w-2.5" />
        live
      </span>
      {revokeButton}
    </div>
  )
}

// ── Flow 1: Claude Code / Cursor ──────────────────────────────────────────────

function Flow1({ apiKeyPrefix }: { apiKeyPrefix: string | null }) {
  const [generated, setGenerated] = useState(false)

  const keyPlaceholder = apiKeyPrefix ? `${apiKeyPrefix}···` : 'cd_mcp_YOUR_KEY'

  const claudeConfig = `{
  "mcpServers": {
    "cloud-decoded": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "${MCP_ENDPOINT}",
        "--header",
        "Authorization: Bearer ${keyPlaceholder}"
      ]
    }
  }
}`

  const cursorConfig = `{
  "mcpServers": {
    "cloud-decoded": {
      "url": "${MCP_ENDPOINT}",
      "headers": {
        "Authorization": "Bearer ${keyPlaceholder}"
      }
    }
  }
}`

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h3 className="text-sm font-semibold text-zinc-100 mb-1.5">
          Connect to Claude Code or Cursor
        </h3>
        <p className="text-xs text-zinc-500 leading-5">
          Surface incident approvals directly in your AI coding tool. Approve or reject
          proposed fixes without leaving your editor. Requires an API key — generate one
          in the{' '}
          <span className="text-zinc-400">Direct MCP endpoint</span> tab first.
        </p>
      </div>

      {!generated ? (
        <div className="rounded-md border border-zinc-800 bg-zinc-900/40 px-4 py-4 flex flex-col gap-3">
          <p className="text-xs text-zinc-500">
            {apiKeyPrefix
              ? `Your key ${keyPlaceholder} will be pre-filled in the snippet.`
              : 'Generate an API key in the Direct MCP tab, then come back here to get a pre-filled config.'}
          </p>
          <Button
            size="sm"
            className="w-fit bg-blue-600 hover:bg-blue-700 text-white text-xs"
            onClick={() => setGenerated(true)}
          >
            Generate config
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div>
            <p className="text-xs text-zinc-500 mb-2">
              Claude Desktop — paste into{' '}
              <code className="text-zinc-300 text-[11px] bg-zinc-800/80 px-1.5 py-0.5 rounded">
                ~/Library/Application Support/Claude/claude_desktop_config.json
              </code>
            </p>
            <CodeBlock code={claudeConfig} label="claude_desktop_config.json" />
          </div>
          <div>
            <p className="text-xs text-zinc-500 mb-2">
              Cursor — paste into{' '}
              <code className="text-zinc-300 text-[11px] bg-zinc-800/80 px-1.5 py-0.5 rounded">
                .cursor/mcp.json
              </code>
            </p>
            <CodeBlock code={cursorConfig} label=".cursor/mcp.json" />
          </div>
          <ol className="flex flex-col gap-1 text-xs text-zinc-500 list-decimal list-inside leading-6 pl-1">
            <li>
              Replace{' '}
              <code className="text-zinc-400 text-[11px] bg-zinc-800/80 px-1 rounded">
                {keyPlaceholder}
              </code>{' '}
              with your full API key
            </li>
            <li>Restart Claude Desktop or Cursor</li>
            <li>
              Ask Claude:{' '}
              <span className="italic text-zinc-400">
                &ldquo;List my pending Cloud Decoded incidents&rdquo;
              </span>
            </li>
          </ol>
        </div>
      )}

      <div className="flex items-center gap-2 rounded-md border border-zinc-800/60 bg-zinc-900/30 px-3 py-2.5">
        <span className="h-1.5 w-1.5 rounded-full bg-zinc-600 flex-shrink-0" />
        <span className="text-xs text-zinc-600">Waiting for first connection...</span>
      </div>
    </div>
  )
}

// ── Flow 2: Embed in your tools ───────────────────────────────────────────────

function Flow2({ token, apiKeyPrefix }: { token: string; apiKeyPrefix: string | null }) {
  const [subTab, setSubTab] = useState<EmbedSubTab>('mcp_sdk')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  const keyPlaceholder = apiKeyPrefix ? `${apiKeyPrefix}···` : 'cd_mcp_YOUR_KEY'
  const apiBase =
    (process.env.NEXT_PUBLIC_API_URL ?? 'https://api.theclouddecoded.com') + '/api/v1'

  const pythonSnippet = `from mcp import ClientSession
from mcp.client.sse import sse_client

async with sse_client(
    url="${MCP_ENDPOINT}",
    headers={"Authorization": "Bearer ${keyPlaceholder}"},
) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("list_incidents")
        print(result.content)`

  const nodeSnippet = `import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";

const transport = new SSEClientTransport(
  new URL("${MCP_ENDPOINT}"),
  { headers: { Authorization: "Bearer ${keyPlaceholder}" } }
);
const client = new Client({ name: "my-app", version: "1.0.0" }, {});
await client.connect(transport);
const result = await client.callTool("list_incidents", {});
console.log(result.content);`

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    const r = await testMCPConnection(token)
    setTestResult(r)
    setTesting(false)
  }

  const REST_ENDPOINTS = [
    ['GET',  '/incidents',               'list incident queue'],
    ['GET',  '/incidents/{id}',          'incident detail + options'],
    ['POST', '/incidents/{id}/approve',  'HITL approval gate'],
    ['POST', '/incidents/{id}/reject',   'reject proposed fix'],
    ['GET',  '/agents',                  'available agents'],
    ['GET',  '/outreach/pacing',         'outreach send limits'],
  ] as const

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h3 className="text-sm font-semibold text-zinc-100 mb-1.5">
          Embed in your internal tooling
        </h3>
        <p className="text-xs text-zinc-500 leading-5">
          Call Cloud Decoded from your own dashboards, scripts, or internal tools.
          Choose the MCP SDK (recommended) or plain REST.
        </p>
      </div>

      <div className="flex gap-0.5 rounded-md border border-zinc-800 bg-zinc-900/40 p-1 w-fit">
        {([['mcp_sdk', 'MCP SDK'], ['rest', 'REST API']] as const).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setSubTab(id)}
            className={cn(
              'px-3 py-1 text-xs font-medium rounded transition-colors',
              subTab === id ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-500 hover:text-zinc-300',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {subTab === 'mcp_sdk' ? (
        <div className="flex flex-col gap-4">
          <div>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wider mb-2">MCP endpoint</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded border border-zinc-800 bg-zinc-900 px-3 py-2 text-xs font-mono text-blue-300 overflow-x-auto">
                {MCP_ENDPOINT}
              </code>
              <CopyButton text={MCP_ENDPOINT} />
            </div>
          </div>
          <CodeBlock code={pythonSnippet} label="Python — pip install mcp" />
          <CodeBlock code={nodeSnippet} label="Node.js — npm install @modelcontextprotocol/sdk" />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wider mb-2">API base URL</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded border border-zinc-800 bg-zinc-900 px-3 py-2 text-xs font-mono text-blue-300 overflow-x-auto">
                {apiBase}
              </code>
              <CopyButton text={apiBase} />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            {REST_ENDPOINTS.map(([method, path, desc]) => (
              <div
                key={path}
                className="flex items-center gap-3 rounded border border-zinc-800/50 bg-zinc-900/30 px-3 py-2 text-xs font-mono"
              >
                <span
                  className={cn(
                    'w-10 text-center rounded text-[10px] font-semibold py-0.5 flex-shrink-0',
                    method === 'GET'
                      ? 'bg-blue-900/50 text-blue-300'
                      : 'bg-green-900/50 text-green-300',
                  )}
                >
                  {method}
                </span>
                <span className="text-zinc-400">{path}</span>
                <span className="ml-auto text-zinc-600 text-[10px] hidden lg:inline">{desc}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-zinc-600">
            Pass{' '}
            <code className="text-zinc-500 text-[11px]">
              X-Workspace-Token: {'<your-token>'}
            </code>{' '}
            on every request.
          </p>
        </div>
      )}

      <div className="flex items-center gap-3 pt-2 border-t border-zinc-800/60">
        <Button
          size="sm"
          variant="outline"
          className="border-zinc-700 text-xs h-7"
          disabled={testing}
          onClick={handleTest}
        >
          {testing && <RefreshCw className="h-3 w-3 animate-spin mr-1.5" />}
          Test connection
        </Button>
        {testResult && (
          <span
            className={cn(
              'text-xs flex items-center gap-1',
              testResult.ok ? 'text-green-400' : 'text-red-400',
            )}
          >
            {testResult.ok ? (
              <Check className="h-3 w-3" />
            ) : (
              <AlertTriangle className="h-3 w-3" />
            )}
            {testResult.message}
          </span>
        )}
      </div>
    </div>
  )
}

// ── KeyCard ───────────────────────────────────────────────────────────────────

function KeyCard({
  k,
  onRevoke,
}: {
  k: MCPApiKey
  onRevoke: (id: string) => Promise<void>
}) {
  const [confirming, setConfirming] = useState(false)
  const [revoking, setRevoking] = useState(false)

  const daysLeft = Math.ceil(
    (new Date(k.expires_at).getTime() - Date.now()) / (24 * 3600 * 1000),
  )
  const expiringSoon = daysLeft <= 7 && daysLeft > 0

  return (
    <div className="flex items-center gap-3 rounded-md border border-zinc-800 bg-zinc-900/40 px-3 py-2.5">
      <Key className="h-3.5 w-3.5 text-zinc-600 flex-shrink-0" />
      <div className="flex flex-col gap-0.5 flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-zinc-200 truncate">{k.name}</span>
          <code className="text-[10px] font-mono text-zinc-500 bg-zinc-800 px-1.5 py-0.5 rounded flex-shrink-0">
            {k.key_prefix}···
          </code>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-zinc-600 flex-wrap">
          <span>{k.scopes.join(', ')}</span>
          <span
            className={cn(
              expiringSoon ? 'text-amber-500' : '',
              k.is_expired ? 'text-red-400' : '',
            )}
          >
            {k.is_expired ? 'Expired' : `${daysLeft}d remaining`}
          </span>
          {k.last_used_at && (
            <span>Last used {new Date(k.last_used_at).toLocaleDateString()}</span>
          )}
        </div>
      </div>
      {!confirming ? (
        <button
          className="flex-shrink-0 text-[10px] text-zinc-600 hover:text-red-400 transition-colors"
          onClick={() => setConfirming(true)}
        >
          Revoke
        </button>
      ) : (
        <div className="flex-shrink-0 flex items-center gap-1.5 text-[10px]">
          <span className="text-zinc-400">Sure?</span>
          <button
            className="text-red-400 hover:text-red-300 disabled:opacity-40"
            disabled={revoking}
            onClick={async () => {
              setRevoking(true)
              await onRevoke(k.id)
            }}
          >
            Yes
          </button>
          <span className="text-zinc-700">/</span>
          <button
            className="text-zinc-500 hover:text-zinc-300"
            onClick={() => setConfirming(false)}
          >
            No
          </button>
        </div>
      )}
    </div>
  )
}

// ── Flow 3: Direct MCP endpoint ───────────────────────────────────────────────

function Flow3({
  token,
  keys,
  onGenerateKey,
  onRevokeKey,
  onRevokeAll,
}: {
  token: string
  keys: MCPApiKey[]
  onGenerateKey: (name: string, scopes: string[], expiry_days: number) => Promise<string>
  onRevokeKey: (id: string) => Promise<void>
  onRevokeAll: () => Promise<void>
}) {
  const [newKeyName, setNewKeyName]           = useState('')
  const [wantWrite, setWantWrite]             = useState(false)
  const [showWriteConfirm, setShowWriteConfirm] = useState(false)
  const [newKeyExpiry, setNewKeyExpiry]       = useState<30 | 60 | 90>(30)
  const [generating, setGenerating]           = useState(false)
  const [newRawKey, setNewRawKey]             = useState<string | null>(null)
  const [rawKeyCopied, setRawKeyCopied]       = useState(false)
  const [revokeAllConfirm, setRevokeAllConfirm] = useState(false)
  const [testing, setTesting]                 = useState(false)
  const [testResult, setTestResult]           = useState<{ ok: boolean; message: string } | null>(null)

  const scopes = wantWrite ? ['mcp:read', 'mcp:write'] : ['mcp:read']

  async function handleGenerate() {
    if (!newKeyName.trim()) return
    setGenerating(true)
    const raw = await onGenerateKey(newKeyName.trim(), scopes, newKeyExpiry)
    setNewRawKey(raw)
    setNewKeyName('')
    setWantWrite(false)
    setNewKeyExpiry(30)
    setGenerating(false)
  }

  async function copyRaw() {
    if (!newRawKey) return
    await navigator.clipboard.writeText(newRawKey)
    setRawKeyCopied(true)
    setTimeout(() => setRawKeyCopied(false), 2000)
  }

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    const r = await testMCPConnection(token)
    setTestResult(r)
    setTesting(false)
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h3 className="text-sm font-semibold text-zinc-100 mb-1.5">Direct MCP endpoint</h3>
        <p className="text-xs text-zinc-500 leading-5">
          Connect any MCP-compatible client directly. Use OAuth 2.1 (Enterprise) or
          API keys (Starter / Growth) for authentication.
        </p>
      </div>

      {/* Endpoint info */}
      <div className="flex flex-col gap-3">
        {[
          ['MCP endpoint',                MCP_ENDPOINT],
          ['OAuth 2.1 authorization URL', OAUTH_AUTH_URL],
        ].map(([label, url]) => (
          <div key={label}>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wider mb-1.5">{label}</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded border border-zinc-800 bg-zinc-900 px-3 py-2 text-xs font-mono text-blue-300 overflow-x-auto">
                {url}
              </code>
              <CopyButton text={url} />
            </div>
          </div>
        ))}
        <div>
          <p className="text-[10px] text-zinc-600 uppercase tracking-wider mb-1.5">
            Available scopes
          </p>
          <div className="flex gap-2">
            {['mcp:read', 'mcp:write'].map(scope => (
              <span
                key={scope}
                className="rounded border border-zinc-800 bg-zinc-900/50 px-2.5 py-1 text-[11px] font-mono text-zinc-400"
              >
                {scope}
              </span>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-3 pt-1">
          <Button
            size="sm"
            variant="outline"
            className="border-zinc-700 text-xs h-7"
            disabled={testing}
            onClick={handleTest}
          >
            {testing && <RefreshCw className="h-3 w-3 animate-spin mr-1.5" />}
            Test connection
          </Button>
          {testResult && (
            <span
              className={cn(
                'text-xs flex items-center gap-1',
                testResult.ok ? 'text-green-400' : 'text-red-400',
              )}
            >
              {testResult.ok ? (
                <Check className="h-3 w-3" />
              ) : (
                <AlertTriangle className="h-3 w-3" />
              )}
              {testResult.message}
            </span>
          )}
        </div>
      </div>

      <div className="border-t border-zinc-800" />

      {/* API key management */}
      <div className="flex flex-col gap-4">
        <p className="text-[10px] text-zinc-600 uppercase tracking-wider">
          API keys (Starter / Growth)
        </p>

        {/* One-time raw key banner */}
        {newRawKey && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-3 flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-400 flex-shrink-0" />
              <span className="text-xs text-amber-300 font-medium">
                Copy this key now — it will not be shown again
              </span>
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded border border-amber-500/20 bg-zinc-950 px-3 py-2 text-xs font-mono text-amber-300 overflow-x-auto">
                {newRawKey}
              </code>
              <button
                onClick={copyRaw}
                className="flex items-center gap-1 text-xs text-amber-400 hover:text-amber-200 transition-colors flex-shrink-0"
              >
                {rawKeyCopied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                {rawKeyCopied ? 'Copied!' : 'Copy key'}
              </button>
            </div>
            <button
              className="text-[10px] text-zinc-600 hover:text-zinc-400 text-left transition-colors"
              onClick={() => setNewRawKey(null)}
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Existing keys */}
        {keys.length > 0 ? (
          <div className="flex flex-col gap-2">
            {keys.map(k => (
              <KeyCard key={k.id} k={k} onRevoke={onRevokeKey} />
            ))}
          </div>
        ) : (
          !newRawKey && (
            <p className="text-xs text-zinc-600 italic">
              No active API keys. Generate one below.
            </p>
          )
        )}

        {/* Generate new key form */}
        <div className="rounded-md border border-zinc-800 bg-zinc-900/30 px-4 py-4 flex flex-col gap-3">
          <p className="text-[10px] text-zinc-600 uppercase tracking-wider">New key</p>
          <input
            value={newKeyName}
            onChange={e => setNewKeyName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleGenerate()}
            placeholder="Key name — e.g. Claude Code / prod"
            className="w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs text-zinc-200 placeholder:text-zinc-600 outline-none focus:border-zinc-500 transition-colors"
          />

          {/* Scope selector */}
          <div className="flex flex-col gap-1.5">
            <p className="text-[10px] text-zinc-600">Scopes</p>
            <div className="flex gap-2 flex-wrap">
              <button
                onClick={() => {
                  setWantWrite(false)
                  setShowWriteConfirm(false)
                }}
                className={cn(
                  'flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs transition-colors',
                  !wantWrite
                    ? 'border-blue-500/50 bg-blue-500/10 text-blue-300'
                    : 'border-zinc-700 text-zinc-500 hover:border-zinc-600 hover:text-zinc-400',
                )}
              >
                <span className="font-mono">mcp:read</span>
                {!wantWrite && <Check className="h-3 w-3" />}
              </button>
              <button
                onClick={() => {
                  if (!wantWrite) setShowWriteConfirm(true)
                  else setWantWrite(false)
                }}
                className={cn(
                  'flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs transition-colors',
                  wantWrite
                    ? 'border-amber-500/50 bg-amber-500/10 text-amber-300'
                    : 'border-zinc-700 text-zinc-500 hover:border-zinc-600 hover:text-zinc-400',
                )}
              >
                <span className="font-mono">mcp:write</span>
                {wantWrite && <Check className="h-3 w-3" />}
              </button>
            </div>

            {/* Write scope confirm inline */}
            {showWriteConfirm && !wantWrite && (
              <div className="rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2.5 flex flex-col gap-2">
                <p className="text-xs text-amber-300">
                  Write scope allows approving and rejecting incidents via MCP.
                  Only enable this for tools and integrations you control.
                </p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    className="h-6 text-[11px] bg-amber-600 hover:bg-amber-700 text-white"
                    onClick={() => {
                      setWantWrite(true)
                      setShowWriteConfirm(false)
                    }}
                  >
                    Enable write scope
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 text-[11px] text-zinc-500 hover:text-zinc-300"
                    onClick={() => setShowWriteConfirm(false)}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </div>

          {/* Expiry selector */}
          <div className="flex flex-col gap-1.5">
            <p className="text-[10px] text-zinc-600">Expiry (max 90 days — no permanent keys)</p>
            <div className="flex gap-2">
              {([30, 60, 90] as const).map(d => (
                <button
                  key={d}
                  onClick={() => setNewKeyExpiry(d)}
                  className={cn(
                    'rounded border px-3 py-1.5 text-xs transition-colors',
                    newKeyExpiry === d
                      ? 'border-zinc-500 bg-zinc-700 text-zinc-100'
                      : 'border-zinc-700 text-zinc-500 hover:border-zinc-600 hover:text-zinc-400',
                  )}
                >
                  {d}d
                </button>
              ))}
            </div>
          </div>

          <Button
            size="sm"
            className="w-fit bg-zinc-700 hover:bg-zinc-600 text-zinc-100 text-xs"
            disabled={!newKeyName.trim() || generating}
            onClick={handleGenerate}
          >
            {generating ? (
              <>
                <RefreshCw className="h-3 w-3 animate-spin mr-1.5" />
                Generating...
              </>
            ) : (
              <>
                <Plus className="h-3 w-3 mr-1.5" />
                Generate key
              </>
            )}
          </Button>
        </div>

        {/* Emergency stop */}
        {keys.length > 0 && (
          <div className="flex items-center gap-3 pt-1 border-t border-zinc-800/60">
            {!revokeAllConfirm ? (
              <button
                className="text-xs text-zinc-600 hover:text-red-400 transition-colors"
                onClick={() => setRevokeAllConfirm(true)}
              >
                Revoke all connections
              </button>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-red-400">
                  Invalidates all {keys.length} key{keys.length !== 1 ? 's' : ''}. Continue?
                </span>
                <button
                  className="text-xs text-red-400 hover:text-red-300 font-medium"
                  onClick={async () => {
                    await onRevokeAll()
                    setRevokeAllConfirm(false)
                  }}
                >
                  Yes, revoke all
                </button>
                <button
                  className="text-xs text-zinc-500 hover:text-zinc-300"
                  onClick={() => setRevokeAllConfirm(false)}
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

const STATUS_POLL_MS = 15_000

const FLOWS: Array<{ id: FlowId; label: string; Icon: IconComponent; badge?: string }> = [
  { id: 'claude_code', label: 'Claude Code / Cursor', Icon: Terminal },
  { id: 'embed',       label: 'Embed in your tools',  Icon: Code2 },
  { id: 'direct',      label: 'Direct MCP endpoint',  Icon: Plug,   badge: 'Advanced' },
]

export function IntegrationsDashboard({ token }: { token: string }) {
  const [activeFlow, setActiveFlow] = useState<FlowId>('claude_code')
  const [status, setStatus]         = useState<MCPConnectionStatus | null>(null)
  const [keys, setKeys]             = useState<MCPApiKey[]>([])

  // Initial load: keys (once) + status (then poll)
  useEffect(() => {
    let cancelled = false

    async function init() {
      const [fetchedKeys, fetchedStatus] = await Promise.all([
        listMCPKeys(token),
        getMCPStatus(token).catch(() => null),
      ])
      if (cancelled) return
      setKeys(fetchedKeys)
      setStatus(fetchedStatus)
    }

    async function pollStatus() {
      const s = await getMCPStatus(token).catch(() => null)
      if (!cancelled) setStatus(s)
    }

    init()
    const poll = setInterval(pollStatus, STATUS_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(poll)
    }
  }, [token])

  async function handleGenerateKey(
    name: string,
    scopes: string[],
    expiry_days: number,
  ): Promise<string> {
    const result = await generateMCPKey(token, name, scopes, expiry_days)
    setKeys(prev => [result.key, ...prev])
    return result.raw_key
  }

  async function handleRevokeKey(keyId: string) {
    await revokeMCPKey(token, keyId)
    setKeys(prev => prev.filter(k => k.id !== keyId))
  }

  async function handleRevokeAll() {
    await revokeAllMCPKeys(token)
    setKeys([])
    // Refresh status immediately so the bar reflects 0 active connections
    getMCPStatus(token).then(setStatus).catch(() => null)
  }

  const firstActiveKeyPrefix = keys.find(k => !k.is_expired)?.key_prefix ?? null

  return (
    <div className="flex h-full">
      {/* Left nav */}
      <div className="w-52 flex-shrink-0 border-r border-zinc-800 p-3 flex flex-col gap-1">
        <p className="px-2 pt-1 pb-2 text-[10px] text-zinc-600 uppercase tracking-wider">
          Connection type
        </p>
        {FLOWS.map(({ id, label, Icon, badge }) => (
          <button
            key={id}
            onClick={() => setActiveFlow(id)}
            className={cn(
              'flex items-center gap-2.5 rounded px-2.5 py-2 text-xs text-left transition-colors w-full',
              activeFlow === id
                ? 'bg-zinc-800 text-zinc-100'
                : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-900',
            )}
          >
            <Icon className="h-3.5 w-3.5 flex-shrink-0" />
            <span className="flex-1">{label}</span>
            {badge && (
              <span className="text-[9px] rounded border border-zinc-700 px-1 py-0.5 text-zinc-600 flex-shrink-0">
                {badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Right panel */}
      <div className="flex-1 overflow-y-auto p-6 max-w-3xl">
        <StatusBar status={status} onRevokeAll={handleRevokeAll} />

        {activeFlow === 'claude_code' && (
          <Flow1 apiKeyPrefix={firstActiveKeyPrefix} />
        )}
        {activeFlow === 'embed' && (
          <Flow2 token={token} apiKeyPrefix={firstActiveKeyPrefix} />
        )}
        {activeFlow === 'direct' && (
          <Flow3
            token={token}
            keys={keys}
            onGenerateKey={handleGenerateKey}
            onRevokeKey={handleRevokeKey}
            onRevokeAll={handleRevokeAll}
          />
        )}
      </div>
    </div>
  )
}
