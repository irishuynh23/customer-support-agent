import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './App.css'

type Role = 'user' | 'assistant'

interface Message {
  id: string
  role: Role
  content: string
  sources?: string[]
  isStreaming?: boolean
}

interface Conversation {
  id: string
  title: string
  messages: Message[]
  updatedAt: number
}

const API_BASE_URL = 'http://localhost:8000'
const STORAGE_KEY = 'customer-service-agent-conversations'
const SESSION_STORAGE_KEY = 'customer-service-agent-session'

const WELCOME_MESSAGE: Message = {
  id: 'welcome',
  role: 'assistant',
  content:
    'Add one or more website links in the sidebar and click **Load website(s)**. Once the content is indexed, you can ask questions about those sites here.',
  sources: [],
}

function createConversation(id?: string): Conversation {
  return {
    id: id ?? `conv-${Date.now()}`,
    title: 'New chat',
    messages: [WELCOME_MESSAGE],
    updatedAt: Date.now(),
  }
}

function toExternalHref(raw: string): string | null {
  const s = (raw || '').trim()
  if (!s) return null
  try {
    const u = new URL(s)
    if (u.protocol === 'http:' || u.protocol === 'https:') return u.toString()
    return null
  } catch {
    if (/^www\./i.test(s)) return `https://${s}`
    return null
  }
}

function hostLabel(url: string): string {
  try {
    const u = new URL(url)
    return u.hostname
  } catch {
    return url
  }
}

function parseSuggestedTitle(answer: string): string | null {
  const match = answer.match(/\nTITLE:\s*(.+?)(?:\n|$)/i)
  return match ? match[1].trim() : null
}

function stripTitleFromAnswer(answer: string): string {
  return answer.replace(/\nTITLE:\s*.+?(?:\n|$)/i, '').trim()
}

function createBusinessId(): string {
  return `biz-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** Remove "Source: ..." lines from message body; sources are shown in the dropdown. */
function stripSourceLines(content: string): string {
  return content
    .split('\n')
    .filter((line) => !/^\s*Source:\s*.+/.test(line.trim()))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/** True if content looks like contact info (email/phone) that should be plain text, not a code block. */
function looksLikeContactInfo(code: string): boolean {
  const trimmed = code.trim()
  if (trimmed.includes('\n') || trimmed.length > 80) return false
  const emailLike = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)
  const phoneLike = /^[\d\s().\-+]+$/.test(trimmed) && trimmed.length >= 10
  return emailLike || phoneLike
}

function CodeBlockWithCopy({
  language,
  code,
}: {
  language: string | undefined
  code: string
}) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(code)
      } else {
        const textarea = document.createElement('textarea')
        textarea.value = code
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        document.body.removeChild(textarea)
      }
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // ignore
    }
  }

  const languageLabel =
    language && language !== 'text' ? language.charAt(0).toUpperCase() + language.slice(1) : 'Code'

  return (
    <div className="code-block">
      <div className="code-block-header">
        <span className="code-block-lang">{languageLabel}</span>
        <button
          type="button"
          className={`code-copy-button ${copied ? 'copied' : ''}`}
          onClick={handleCopy}
          aria-label={copied ? 'Copied' : 'Copy code'}
          data-tooltip={copied ? 'Copied' : 'Copy'}
        >
          <span className="code-copy-icon" aria-hidden="true">
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="9" y="9" width="13" height="13" rx="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
          </span>
        </button>
      </div>
      <div className="code-block-body code-container">
        <SyntaxHighlighter
          style={vscDarkPlus}
          language={language}
          PreTag="pre"
          wrapLongLines={false}
          customStyle={{
            margin: 0,
            padding: 0,
            background: 'transparent',
            backgroundColor: 'transparent',
            border: 'none',
            boxShadow: 'none',
          }}
          codeTagProps={{
            style: {
              fontSize: 'inherit',
              whiteSpace: 'pre',
            },
          }}
        >
          {code}
        </SyntaxHighlighter>
      </div>
    </div>
  )
}

function shouldIgnoreAutoFocusClick(target: EventTarget | null): boolean {
  if (!target || !(target instanceof Element)) return false
  // Don't steal focus when interacting with controls/links or selecting within the input.
  const interactive = target.closest(
    'a,button,input,textarea,select,summary,details,[role="button"],[contenteditable="true"]'
  )
  return Boolean(interactive)
}

async function ingestUrls(urls: string[], businessId: string) {
  const res = await fetch(`${API_BASE_URL}/api/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ urls, business_id: businessId }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || 'Ingest failed')
  }
  return (await res.json()) as { indexed_pages: number; errors: Array<{ url: string; error: string }> }
}

async function sendPrompt(
  prompt: string,
  history?: { role: Role; content: string }[],
  businessId?: string,
) {
  const res = await fetch(`${API_BASE_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, messages: history ?? null, business_id: businessId ?? null }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || 'Failed to contact backend')
  }
  return (await res.json()) as { answer: string; sources: string[] }
}

async function streamText(
  text: string,
  onChunk: (delta: string) => void,
  chunkSize = 32,
  delayMs = 20
) {
  for (let i = 0; i < text.length; i += chunkSize) {
    const delta = text.slice(i, i + chunkSize)
    onChunk(delta)
    await new Promise((resolve) => setTimeout(resolve, delayMs))
  }
}

function loadConversations(): { conversations: Conversation[]; activeId: string | null } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { conversations: [], activeId: null }
    const data = JSON.parse(raw) as { conversations: Conversation[]; activeId: string | null }
    if (!Array.isArray(data.conversations) || data.conversations.length === 0) {
      return { conversations: [], activeId: null }
    }
    return {
      conversations: data.conversations,
      activeId: data.activeId ?? data.conversations[0].id,
    }
  } catch {
    return { conversations: [], activeId: null }
  }
}

function saveConversations(conversations: Conversation[], activeId: string | null) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ conversations, activeId }))
  } catch {
    // ignore
  }
}

function loadSession(): { ingestedChunks: number; businessId: string | null } {
  try {
    const raw = localStorage.getItem(SESSION_STORAGE_KEY)
    if (!raw) return { ingestedChunks: 0, businessId: null }
    const data = JSON.parse(raw) as { ingestedChunks?: number; businessId?: string | null }
    const ingestedChunks =
      typeof data.ingestedChunks === 'number' && data.ingestedChunks > 0 ? data.ingestedChunks : 0
    const businessId =
      typeof data.businessId === 'string' && data.businessId.trim().length > 0
        ? data.businessId
        : null
    return { ingestedChunks, businessId }
  } catch {
    return { ingestedChunks: 0, businessId: null }
  }
}

function saveSession(ingestedChunks: number, businessId: string | null) {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ ingestedChunks, businessId }))
  } catch {
    // ignore
  }
}

function clearSession() {
  try {
    localStorage.removeItem(SESSION_STORAGE_KEY)
  } catch {
    // ignore
  }
}

function App() {
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const { conversations: loaded } = loadConversations()
    return loaded.length > 0 ? loaded : [createConversation()]
  })
  const [activeId, setActiveId] = useState<string | null>(() => {
    const { conversations: loaded, activeId: id } = loadConversations()
    if (loaded.length > 0) return id ?? loaded[0].id
    return null
  })
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastPrompt, setLastPrompt] = useState<string | null>(null)
  const [lastPromptConversationId, setLastPromptConversationId] = useState<string | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const messagesRef = useRef<HTMLElement | null>(null)
  const [isSidebarOpen, setIsSidebarOpen] = useState(true)

  const [urlInput, setUrlInput] = useState('')
  const [ingestLoading, setIngestLoading] = useState(false)
  const [ingestError, setIngestError] = useState<string | null>(null)
  const [ingestSuccess, setIngestSuccess] = useState<string | null>(null)
  const session = loadSession()
  const [businessId, setBusinessId] = useState<string>(() => {
    return session.businessId ?? createBusinessId()
  })
  const [ingestedChunks, setIngestedChunks] = useState(() => session.ingestedChunks)

  const activeConversation = conversations.find((c) => c.id === activeId) ?? null
  const messages = activeConversation?.messages ?? []
  const hasIngested = ingestedChunks > 0

  useEffect(() => {
    if (conversations.length > 0 && activeId === null) {
      setActiveId(conversations[0].id)
    }
  }, [conversations.length, activeId])

  useEffect(() => {
    if (conversations.length === 0) return
    const id = activeId ?? conversations[0].id
    if (!conversations.some((c) => c.id === id)) {
      setActiveId(conversations[0].id)
    }
    saveConversations(conversations, activeId ?? conversations[0].id)
  }, [conversations, activeId])

  useEffect(() => {
    if (window.innerWidth <= 768) {
      setIsSidebarOpen(false)
    }
  }, [])

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsSidebarOpen(false)
    }
    if (isSidebarOpen) {
      document.addEventListener('keydown', handleEscape)
      return () => document.removeEventListener('keydown', handleEscape)
    }
  }, [isSidebarOpen])

  useEffect(() => {
    saveSession(ingestedChunks, businessId)
  }, [ingestedChunks, businessId])

  const handleResetAllConversations = () => {
    const next = createConversation()
    setConversations([next])
    setActiveId(next.id)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ conversations: [next], activeId: next.id }))
    } catch {
      // ignore
    }
  }

  const handleEndSession = () => {
    clearSession()
    setIngestedChunks(0)
    setIngestSuccess(null)
    setIngestError(null)
    setUrlInput('')
    setBusinessId(createBusinessId())
    const next = createConversation()
    setConversations([next])
    setActiveId(next.id)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ conversations: [next], activeId: next.id }))
    } catch {
      // ignore
    }
  }

  // Scroll to bottom on mount and when messages or streaming content changes
  useEffect(() => {
    const el = messagesRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages])

  // Auto-focus the composer when returning to the tab/window.
  useEffect(() => {
    const handleWindowFocus = () => inputRef.current?.focus()
    window.addEventListener('focus', handleWindowFocus)
    return () => window.removeEventListener('focus', handleWindowFocus)
  }, [])

  useEffect(() => {
    inputRef.current?.focus()
  }, [activeId])

  const handleIngest = async () => {
    const lines = urlInput
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
    if (lines.length === 0) {
      setIngestError('Enter at least one URL.')
      return
    }
    setIngestError(null)
    setIngestSuccess(null)
    setIngestLoading(true)
    try {
      const result = await ingestUrls(lines, businessId)
      setIngestedChunks((prev) => prev + result.indexed_pages)
      if (result.errors.length > 0) {
        setIngestError(result.errors.map((e) => `${e.url}: ${e.error}`).join('; '))
      } else {
        setIngestError(null)
      }
      const totalChunks = ingestedChunks + result.indexed_pages
      if (result.indexed_pages > 0) {
        setIngestSuccess(
          `Done. Crawling and embedding finished. ${result.indexed_pages} chunk(s) added (${totalChunks} total). You can ask questions in the chat below.`
        )
      }
    } catch (err) {
      setIngestError(err instanceof Error ? err.message : 'Failed to load website(s).')
      setIngestSuccess(null)
    } finally {
      setIngestLoading(false)
    }
  }

  const sendMessage = async (rawPrompt: string) => {
    const trimmed = rawPrompt.trim()
    if (!trimmed || isLoading || !activeId) return
    if (!hasIngested) {
      setError('Add and load at least one website link in the sidebar first.')
      return
    }

    setError(null)
    setLastPrompt(trimmed)
    setLastPromptConversationId(activeId)

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: trimmed,
    }

    const assistantId = `assistant-${Date.now()}`
    const initialAssistant: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      sources: [],
      isStreaming: true,
    }

    setConversations((prev) =>
      prev.map((c) =>
        c.id !== activeId
          ? c
          : {
              ...c,
              messages: [...c.messages, userMessage, initialAssistant],
              updatedAt: Date.now(),
            }
      )
    )
    setInput('')
    setIsLoading(true)

    try {
      const { answer, sources } = await sendPrompt(
        trimmed,
        [...(messages || []), userMessage].map((m) => ({ role: m.role, content: m.content })),
        businessId,
      )
      const displayAnswer = stripTitleFromAnswer(answer)
      const suggestedTitle = parseSuggestedTitle(answer)

      await streamText(displayAnswer, (delta) => {
        setConversations((prev) =>
          prev.map((c) => {
            if (c.id !== activeId) return c
            return {
              ...c,
              messages: c.messages.map((m) =>
                m.id === assistantId ? { ...m, content: m.content + delta } : m
              ),
            }
          })
        )
      })

      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== activeId) return c
          const nextMessages = c.messages.map((m) =>
            m.id === assistantId ? { ...m, isStreaming: false, sources } : m
          )
          const title =
            c.title === 'New chat' && suggestedTitle ? suggestedTitle : c.title
          return { ...c, title, messages: nextMessages, updatedAt: Date.now() }
        })
      )
    } catch (err) {
      console.error(err)
      setError('Failed to get a response from the backend.')
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== activeId) return c
          return {
            ...c,
            messages: c.messages.map((m) =>
              m.id === assistantId
                ? { ...m, isStreaming: false, content: m.content || '(Failed to complete response.)' }
                : m
            ),
          }
        })
      )
    } finally {
      setIsLoading(false)
    }
  }

  const handleNewChat = () => {
    const existingEmpty = conversations.find((c) => !c.messages.some((m) => m.role === 'user'))
    if (existingEmpty) {
      setActiveId(existingEmpty.id)
      return
    }
    const next = createConversation()
    setConversations((prev) => [next, ...prev])
    setActiveId(next.id)
  }

  const handleDeleteConversation = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setConversations((prev) => {
      const next = prev.filter((c) => c.id !== id)
      if (next.length === 0) return [createConversation()]
      return next
    })
    if (activeId === id) setActiveId(null)
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    await sendMessage(input)
  }

  const handleRetryLast = async () => {
    if (!lastPrompt || !activeId || lastPromptConversationId !== activeId || isLoading) return
    await sendMessage(lastPrompt)
  }

  const handleComposerKeyDown = async (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      await sendMessage(input)
      return
    }
    if (e.key !== 'Enter') return
    if (e.shiftKey) return
    e.preventDefault()
    await sendMessage(input)
  }

  return (
    <div className={`app-root ${isSidebarOpen ? 'sidebar-open' : 'sidebar-collapsed'}`}>
      {isSidebarOpen && (
        <div
          className="sidebar-backdrop"
          aria-hidden="true"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}
      <aside className="sidebar">
        <button
          type="button"
          className="sidebar-toggle sidebar-close"
          onClick={() => setIsSidebarOpen(false)}
          aria-label="Close sidebar"
          title="Close sidebar"
        >
          <span className="sidebar-toggle-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="5" y="4" width="6" height="16" rx="2" />
              <rect x="13" y="4" width="6" height="16" rx="2" />
            </svg>
          </span>
        </button>
        <div className="sidebar-header">
          <h1 className="sidebar-title">Customer Service Agent</h1>
          <button className="new-chat-button" type="button" onClick={handleNewChat}>
            + New chat
          </button>
        </div>

        <div className="ingest-section">
          <label className="ingest-label" htmlFor="url-input">
            Website links
          </label>
          <textarea
            id="url-input"
            className="ingest-input"
            placeholder={'https://example.com\nhttps://another-site.com'}
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            rows={3}
            disabled={ingestLoading}
          />
          {ingestLoading && (
            <p className="ingest-status ingest-status-loading">Crawling & embedding… (this may take a moment)</p>
          )}
          {ingestError && <p className="ingest-error">{ingestError}</p>}
          {ingestSuccess && !ingestLoading && <p className="ingest-success">{ingestSuccess}</p>}
          <button
            type="button"
            className="new-chat-button ingest-button"
            onClick={handleIngest}
            disabled={ingestLoading}
          >
            {ingestLoading ? 'Loading…' : 'Load website(s)'}
          </button>
          <button
            type="button"
            className="new-chat-button ingest-button end-session-button"
            onClick={handleEndSession}
          >
            End Session
          </button>
        </div>

        <nav className="conversation-list" aria-label="Conversations">
          {conversations.map((c) => (
            <div
              key={c.id}
              role="button"
              tabIndex={0}
              className={`conversation-item ${c.id === activeId ? 'conversation-item-active' : ''}`}
              onClick={() => setActiveId(c.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  setActiveId(c.id)
                }
              }}
            >
              <span className="conversation-item-title" title={c.title}>
                {c.title}
              </span>
              <button
                type="button"
                className="conversation-item-delete"
                aria-label={`Delete ${c.title}`}
                onClick={(e) => handleDeleteConversation(c.id, e)}
              >
                ×
              </button>
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <button
            type="button"
            className="new-chat-button sidebar-reset"
            onClick={handleResetAllConversations}
          >
            Clear chats
          </button>
          <span className="sidebar-note">React + FastAPI · Local demo</span>
        </div>
      </aside>

      <main
        className="chat-container"
        onMouseDown={(e) => {
          // Focus input when clicking anywhere in chat area.
          if (shouldIgnoreAutoFocusClick(e.target)) return
          inputRef.current?.focus()
        }}
      >
        <header className="chat-header">
          <div className="chat-header-left">
            {!isSidebarOpen && (
              <button
                type="button"
                className="sidebar-toggle"
                onClick={() => setIsSidebarOpen(true)}
                aria-label="Open sidebar"
                title="Open sidebar"
              >
                <span className="sidebar-toggle-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="5" y="4" width="6" height="16" rx="2" />
                    <rect x="13" y="4" width="6" height="16" rx="2" />
                  </svg>
                </span>
              </button>
            )}
            <h2 className="chat-title">Customer Service Agent</h2>
          </div>
          <div className="chat-header-right">
            <span className="chat-header-pill" title={hasIngested ? 'Website content is indexed and ready for questions.' : 'Add website links in the sidebar and load them first.'}>
              {hasIngested ? `Knowledge: Ready (${ingestedChunks} chunks)` : 'Add a website to get started'}
            </span>
          </div>
        </header>

        <section
          className="messages"
          aria-label="Chat messages"
          aria-busy={isLoading}
          ref={messagesRef}
        >
          {messages.map((m) => (
            <div
              key={m.id}
              className={`message-row ${m.role === 'user' ? 'message-row-user' : 'message-row-assistant'}`}
            >
              <div className="avatar">{m.role === 'user' ? 'You' : 'AI'}</div>
              <div className="bubble">
                <div className="bubble-content">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ href, children, ...props }) => {
                        const safeHref = href ?? '#'
                        const isMailto = safeHref.startsWith('mailto:')
                        const isTel = safeHref.startsWith('tel:')
                        let label = children
                        if (href && !isMailto && !isTel) {
                          try {
                            const u = new URL(safeHref)
                            const host = u.hostname.replace(/^www\./i, '')
                            if (
                              Array.isArray(children) &&
                              children.length === 1 &&
                              typeof children[0] === 'string' &&
                              children[0] === href
                            ) {
                              label = host || children
                            }
                          } catch {
                            // fall back to original children
                          }
                        }
                        return (
                          <a
                            {...props}
                            href={safeHref}
                            target={isMailto || isTel ? undefined : '_blank'}
                            rel={isMailto || isTel ? undefined : 'noreferrer'}
                            className="link-chip"
                            title={isMailto || isTel ? safeHref : hostLabel(safeHref)}
                          >
                            {label}
                          </a>
                        )
                      },
                      code: ({ inline, className, children, ...props }) => {
                        const match = /language-([\w-]+)/.exec(className || '')
                        const language = match?.[1]
                        const code = String(children ?? '').replace(/\n$/, '')
                        if (inline) {
                          return (
                            <code className={className} {...props}>
                              {children}
                            </code>
                          )
                        }
                        if (looksLikeContactInfo(code)) {
                          return <span className="bubble-content-plain">{code}</span>
                        }
                        return <CodeBlockWithCopy language={language} code={code} />
                      },
                    }}
                  >
                    {stripSourceLines(m.content || '')}
                  </ReactMarkdown>
                </div>
                {m.isStreaming && (
                  <div className="bubble-loading" aria-hidden="true">
                    <span className="dots">
                      <span />
                      <span />
                      <span />
                    </span>
                  </div>
                )}
                {m.sources && m.sources.length > 0 && (
                  <details className="sources-dropdown">
                    <summary className="sources-dropdown-summary">
                      <span className="sources-dropdown-label">Sources</span>
                      <span className="sources-dropdown-count">({m.sources.length})</span>
                      <span className="sources-dropdown-chevron" aria-hidden="true">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="6 9 12 15 18 9" />
                        </svg>
                      </span>
                    </summary>
                    <ul className="sources-dropdown-list">
                      {m.sources.map((s, idx) => (
                        <li key={idx}>
                          {toExternalHref(s) ? (
                            <a
                              href={toExternalHref(s) as string}
                              target="_blank"
                              rel="noreferrer"
                              title={hostLabel(toExternalHref(s) as string)}
                            >
                              {s}
                            </a>
                          ) : (
                            s
                          )}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            </div>
          ))}
          <div style={{ height: '0.5rem' }} />
        </section>

        <footer className="composer">
          {error && (
            <div className="error-banner" role="alert" aria-live="assertive">
              <span className="error-banner-message">{error}</span>
              <div className="error-banner-actions">
                {lastPrompt && lastPromptConversationId === activeId && (
                  <button
                    type="button"
                    className="error-retry"
                    onClick={handleRetryLast}
                    disabled={isLoading}
                  >
                    Retry last question
                  </button>
                )}
                <button
                  type="button"
                  className="error-banner-dismiss"
                  onClick={() => setError(null)}
                  aria-label="Dismiss error"
                >
                  ×
                </button>
              </div>
            </div>
          )}
          <form onSubmit={handleSubmit} className="composer-form" aria-label="Send a message">
            <textarea
              className="composer-input"
              placeholder={hasIngested ? 'Ask a question about the loaded website(s)… (Enter to send, Shift+Enter for new line)' : 'Add website links in the sidebar first…'}
              value={input}
              ref={inputRef}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleComposerKeyDown}
              rows={2}
              aria-label="Message input"
            />
            <button
              className="composer-send"
              type="submit"
              disabled={isLoading || !input.trim() || !hasIngested}
              title={hasIngested ? 'Send (Enter)' : 'Add a website first'}
              aria-label={isLoading ? 'Sending…' : 'Send message'}
            >
              {isLoading ? 'Sending…' : 'Send'}
            </button>
          </form>
        </footer>
      </main>
    </div>
  )
}

export default App
