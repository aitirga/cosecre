/**
 * A tiny maths-expression evaluator for plot specs.
 *
 * NEVER `eval`, NEVER `new Function`. The strings this parses are written by a
 * language model, and a model that has been steered by a student's text is not
 * a trusted source. Shunting-yard into an RPN stack over a fixed operator and
 * function table is the whole implementation, and nothing outside that table
 * can be reached — no identifiers, no property access, no calls.
 *
 * An expression it cannot parse throws, and the caller renders the raw spec
 * with a "regenerate" button rather than a blank box.
 */

export class ExpressionError extends Error {}

type Token =
  | { type: 'number'; value: number }
  | { type: 'variable' }
  | { type: 'operator'; value: string }
  | { type: 'function'; value: string }
  | { type: 'paren'; value: '(' | ')' }
  | { type: 'comma' }

const FUNCTIONS: Record<string, (...args: number[]) => number> = {
  sin: Math.sin,
  cos: Math.cos,
  tan: Math.tan,
  asin: Math.asin,
  acos: Math.acos,
  atan: Math.atan,
  sqrt: Math.sqrt,
  abs: Math.abs,
  exp: Math.exp,
  ln: Math.log,
  log: Math.log10,
  floor: Math.floor,
  ceil: Math.ceil,
  min: Math.min,
  max: Math.max,
}

const CONSTANTS: Record<string, number> = { pi: Math.PI, e: Math.E }

/** Precedence, and whether equal precedence associates right (only `^` does). */
const OPERATORS: Record<string, { precedence: number; rightAssociative: boolean }> = {
  '+': { precedence: 1, rightAssociative: false },
  '-': { precedence: 1, rightAssociative: false },
  '*': { precedence: 2, rightAssociative: false },
  '/': { precedence: 2, rightAssociative: false },
  '%': { precedence: 2, rightAssociative: false },
  '^': { precedence: 4, rightAssociative: true },
  // Unary minus, produced by the tokeniser — never written by the author.
  'u-': { precedence: 3, rightAssociative: true },
}

function tokenize(source: string): Token[] {
  const tokens: Token[] = []
  let index = 0

  while (index < source.length) {
    const char = source[index]

    if (/\s/.test(char)) {
      index += 1
      continue
    }

    if (/[0-9.]/.test(char)) {
      const match = /^[0-9]*\.?[0-9]+([eE][+-]?[0-9]+)?/.exec(source.slice(index))
      if (!match) throw new ExpressionError(`Número invàlid a la posició ${index}`)
      tokens.push({ type: 'number', value: Number(match[0]) })
      index += match[0].length
      continue
    }

    if (/[a-zA-Z]/.test(char)) {
      const name = /^[a-zA-Z]+/.exec(source.slice(index))![0]
      index += name.length
      const lower = name.toLowerCase()
      if (lower === 'x') tokens.push({ type: 'variable' })
      else if (lower in CONSTANTS) tokens.push({ type: 'number', value: CONSTANTS[lower] })
      else if (lower in FUNCTIONS) tokens.push({ type: 'function', value: lower })
      else throw new ExpressionError(`No conec «${name}»`)
      continue
    }

    if (char === '(' || char === ')') {
      tokens.push({ type: 'paren', value: char })
      index += 1
      continue
    }

    if (char === ',') {
      tokens.push({ type: 'comma' })
      index += 1
      continue
    }

    if (char in OPERATORS && char !== 'u-') {
      // A minus is unary when nothing that could be a left operand precedes it.
      const previous = tokens[tokens.length - 1]
      const isUnary =
        char === '-' &&
        (previous === undefined ||
          previous.type === 'operator' ||
          previous.type === 'comma' ||
          (previous.type === 'paren' && previous.value === '('))
      tokens.push({ type: 'operator', value: isUnary ? 'u-' : char })
      index += 1
      continue
    }

    throw new ExpressionError(`Caràcter inesperat «${char}»`)
  }

  return tokens
}

/** Shunting-yard: infix tokens to RPN. */
function toRpn(tokens: Token[]): Token[] {
  const output: Token[] = []
  const stack: Token[] = []

  for (const token of tokens) {
    switch (token.type) {
      case 'number':
      case 'variable':
        output.push(token)
        break
      case 'function':
        stack.push(token)
        break
      case 'comma':
      case 'operator': {
        if (token.type === 'comma') {
          while (stack.length && !(stack[stack.length - 1].type === 'paren')) {
            output.push(stack.pop()!)
          }
          break
        }
        const current = OPERATORS[token.value]
        while (stack.length) {
          const top = stack[stack.length - 1]
          if (top.type !== 'operator') break
          const other = OPERATORS[top.value]
          const takes = current.rightAssociative
            ? other.precedence > current.precedence
            : other.precedence >= current.precedence
          if (!takes) break
          output.push(stack.pop()!)
        }
        stack.push(token)
        break
      }
      case 'paren':
        if (token.value === '(') {
          stack.push(token)
          break
        }
        while (stack.length && !(stack[stack.length - 1].type === 'paren')) {
          output.push(stack.pop()!)
        }
        if (!stack.length) throw new ExpressionError('Falta un parèntesi obert')
        stack.pop()
        if (stack.length && stack[stack.length - 1].type === 'function') {
          output.push(stack.pop()!)
        }
        break
    }
  }

  while (stack.length) {
    const top = stack.pop()!
    if (top.type === 'paren') throw new ExpressionError('Falta un parèntesi tancat')
    output.push(top)
  }

  return output
}

export interface CompiledExpression {
  (x: number): number
}

/**
 * Parse once, evaluate many times.
 *
 * A plot samples a few hundred points, and re-tokenising per sample would be
 * the only slow thing in the renderer.
 */
export function compileExpression(source: string): CompiledExpression {
  const rpn = toRpn(tokenize(source))
  if (!rpn.length) throw new ExpressionError('Expressió buida')

  return (x: number) => {
    const stack: number[] = []

    for (const token of rpn) {
      if (token.type === 'number') {
        stack.push(token.value)
      } else if (token.type === 'variable') {
        stack.push(x)
      } else if (token.type === 'operator') {
        if (token.value === 'u-') {
          const value = stack.pop()
          if (value === undefined) throw new ExpressionError('Falta un operand')
          stack.push(-value)
          continue
        }
        const right = stack.pop()
        const left = stack.pop()
        if (left === undefined || right === undefined) {
          throw new ExpressionError('Falta un operand')
        }
        switch (token.value) {
          case '+':
            stack.push(left + right)
            break
          case '/':
            stack.push(left / right)
            break
          case '-':
            stack.push(left - right)
            break
          case '*':
            stack.push(left * right)
            break
          case '%':
            stack.push(left % right)
            break
          case '^':
            stack.push(left ** right)
            break
        }
      } else if (token.type === 'function') {
        const fn = FUNCTIONS[token.value]
        // `min` and `max` are the only variadic ones, and the RPN has lost how
        // many arguments were written — so they take the two on the stack,
        // which is what every generated spec actually uses.
        const arity = token.value === 'min' || token.value === 'max' ? 2 : 1
        const args = stack.splice(-arity)
        if (args.length !== arity) throw new ExpressionError('Falten arguments')
        stack.push(fn(...args))
      }
    }

    if (stack.length !== 1) throw new ExpressionError('Expressió mal formada')
    return stack[0]
  }
}
