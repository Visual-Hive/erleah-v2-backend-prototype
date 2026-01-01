# Getting Started with Cline Development

This guide shows you how to vibe code the Erleah backend using Cline.

## Prerequisites

1. ✅ VSCode installed
2. ✅ Cline extension installed
3. ✅ Docker Desktop running
4. ✅ Anthropic API key ready

## Setup (5 minutes)

### 1. Environment Setup

```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your API key
# ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### 2. Start Databases

```bash
# Start PostgreSQL, Qdrant, and Redis
docker-compose up -d

# Verify they're running
docker-compose ps
```

### 3. Install Dependencies

```bash
# Using uv (recommended - it's fast!)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync

# Or using pip
pip install -e .
```

### 4. Test the Server

```bash
# Start the server
uvicorn src.main:app --reload

# In another terminal, test it
curl http://localhost:8000/health
```

You should see: `{"status":"healthy", ...}`

## Vibe Coding with Cline

### Example Session 1: Add a Map Navigation Tool

**You:** "Hey Cline, I need to add a map navigation tool that calculates routes between locations. Check the .clinerules for the pattern."

**Cline will:**
1. Read `.clinerules` for tool development patterns
2. Create `src/tools/map_navigation.py` following the `ErleahBaseTool` pattern
3. Implement A* pathfinding or similar
4. Add the tool to `src/agent/graph.py` TOOLS list
5. Create tests in `tests/test_tools.py`

**You:** "Great! Now let's test it with a real query."

**Cline will:**
1. Start the server if not running
2. Send a test request using the map navigation tool
3. Show you the results

### Example Session 2: Add Vision Analysis

**You:** "Can you add a tool that uses Claude's vision to analyze floor plan images?"

**Cline will:**
1. Create `src/tools/vision_analysis.py`
2. Use the Anthropic messages API with image input
3. Extract coordinates and nearby points from floor plan
4. Return structured data
5. Add to tool registry

### Example Session 3: Improve Agent Planning

**You:** "The agent isn't planning well. Can we add a dedicated planning phase that's more structured?"

**Cline will:**
1. Modify `src/agent/graph.py`
2. Enhance the `plan_actions` node
3. Add better prompting for Claude to create step-by-step plans
4. Maybe add a reflection loop
5. Test with complex queries

## Common Cline Prompts

### Adding Tools
> "Create a tool that [does X]. Follow the pattern in .clinerules"

> "Add a proximity detection tool that finds nearby exhibitors"

> "Build a schedule conflict checker tool"

### Improving the Agent
> "The agent is using too many tools. Can we make it more efficient?"

> "Add a reflection step where the agent checks if it has enough info"

> "Make the planning phase output a structured list of steps"

### Debugging
> "The vector search isn't working well. Can you check the implementation?"

> "I'm getting a pydantic validation error. Can you fix it?"

> "The agent is stuck in a loop. Add a max iteration check"

### Testing
> "Write tests for the map navigation tool"

> "Add integration tests for the full agent flow"

> "Create a test that simulates a complex user query"

## Cline Best Practices

### ✅ Do

1. **Reference .clinerules** - Always ask Cline to check it first
2. **Start small** - Build one tool at a time
3. **Test immediately** - Ask Cline to test after implementing
4. **Iterate** - If something doesn't work, refine with Cline
5. **Ask for explanations** - "Can you explain how this works?"

### ❌ Don't

1. **Don't skip .clinerules** - It has important patterns
2. **Don't implement everything at once** - Vibe code is iterative
3. **Don't ignore errors** - Ask Cline to fix them
4. **Don't forget tests** - Cline can write them easily

## Development Workflow

### Typical Vibe Coding Session

```
1. Idea 💡
   "I want to add X feature"

2. Discuss with Cline 💬
   Cline reads .clinerules and suggests approach

3. Implement 🛠️
   Cline writes the code

4. Test 🧪
   Cline runs tests and shows results

5. Iterate 🔄
   Refine based on results

6. Move to next feature ➡️
```

## Debugging with Cline

### Server won't start

**You:** "Server is crashing on startup. Can you check the logs and fix?"

**Cline:** [Reads logs, identifies issue, fixes it]

### Tool not being called

**You:** "The agent isn't using my new tool. Why?"

**Cline:** [Checks tool description, improves it to be clearer for the LLM]

### Slow responses

**You:** "Responses are slow. Can we optimize?"

**Cline:** [Adds caching, optimizes tool calls, suggests prompt caching]

## Testing Queries

Try these with your running server:

```bash
# Find Python developers
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Find Python developers at the conference",
    "user_context": {"user_id": "test-user"}
  }'

# Complex query
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Find ML sessions happening today, then suggest which Python developers I should meet",
    "user_context": {"user_id": "test-user", "location": "Hall A"}
  }'
```

## Next Steps

### Week 1: Core Tools (with Cline)
- [ ] Implement real vector search (Qdrant integration)
- [ ] Add map navigation with pathfinding
- [ ] Create proximity detection tool
- [ ] Build schedule checker

### Week 2: Vision & Navigation (with Cline)
- [ ] Vision tool for floor plan analysis
- [ ] Route optimization
- [ ] Nearby points of interest
- [ ] Accessibility routing

### Week 3: Advanced Agent (with Cline)
- [ ] Improve planning phase
- [ ] Add reflection loop
- [ ] Implement parallel tool execution
- [ ] Add agent memory/context

### Week 4: Polish & Production (with Cline)
- [ ] Comprehensive testing
- [ ] Error handling
- [ ] Performance optimization
- [ ] Deployment setup

## Helpful Commands

```bash
# Start development
docker-compose up -d
uvicorn src.main:app --reload

# Run tests
pytest

# Run tests in watch mode
pytest-watch

# Check code formatting
black src/
ruff check src/

# Type checking
mypy src/

# View logs
docker-compose logs -f

# Restart a service
docker-compose restart qdrant

# Stop everything
docker-compose down
```

## Connecting to Noodl Frontend

Once you have the backend running, connect it to your Noodl frontend:

1. **In Noodl**, use the SSE Node (AGENT-001)
2. **Set URL** to: `http://localhost:8000/api/chat/stream`
3. **Send message** with user query
4. **Stream response** in real-time

See the Phase 3.5 documentation for full integration guide.

## Pro Tips

### 🎯 Stay Focused
Work on one feature at a time with Cline. Finish it, test it, then move on.

### 💬 Be Specific
"Add a tool that calculates X using Y algorithm" is better than "make it smarter"

### 🧪 Test Everything
Ask Cline to write tests as you go. Prevents bugs later.

### 📖 Use .clinerules
Cline will follow these patterns automatically. They encode best practices.

### 🔄 Iterate Fast
Don't aim for perfection first time. Build → test → refine → repeat.

---

**Ready to build?** Open Cline and say: "Let's build the map navigation tool following .clinerules"

Happy vibe coding! 🚀
