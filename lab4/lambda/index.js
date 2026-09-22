'use strict';

const mysql = require('mysql2/promise');
const Redis = require('ioredis');

// Reusamos conexiones entre invocaciones "warm" del mismo contenedor de Lambda
let dbPool;
let redisClient;
let seeded = false;

const CONTAINER_ID = Math.random().toString(36).slice(2, 10);
const CACHE_TTL = Number(process.env.CACHE_TTL_SECONDS || 300);

function getDbPool() {
  if (!dbPool) {
    dbPool = mysql.createPool({
      host: process.env.DB_HOST,
      port: Number(process.env.DB_PORT || 3306),
      user: process.env.DB_USER,
      password: process.env.DB_PASSWORD,
      database: process.env.DB_NAME,
      connectionLimit: 5,
      connectTimeout: 5000,
    });
  }
  return dbPool;
}

function getRedis() {
  if (!redisClient) {
    redisClient = new Redis({
      host: process.env.REDIS_HOST,
      port: Number(process.env.REDIS_PORT || 6379),
      connectTimeout: 3000,
      maxRetriesPerRequest: 1,
      lazyConnect: true,
    });
  }
  return redisClient;
}

async function ensureSeeded(pool) {
  if (seeded) return;

  await pool.query(`
    CREATE TABLE IF NOT EXISTS products (
      id INT PRIMARY KEY,
      name VARCHAR(100) NOT NULL,
      price DECIMAL(10,2) NOT NULL,
      description VARCHAR(255) NOT NULL
    )
  `);

  const [rows] = await pool.query('SELECT COUNT(*) as c FROM products');
  if (rows[0].c === 0) {
    const values = [];
    for (let i = 1; i <= 20; i++) {
      values.push([i, `Producto ${i}`, (i * 9.99).toFixed(2), `Descripción del producto ${i} - Lab4 DSE`]);
    }
    await pool.query('INSERT INTO products (id, name, price, description) VALUES ?', [values]);
  }
  seeded = true;
}

// La consulta "pesada" a propósito (SLEEP simula un query costoso / join real),
// usada por los dos endpoints para que la comparación sea justa (mismo query).
async function queryProduct(pool, id) {
  const [rows] = await pool.query(
    'SELECT id, name, price, description, SLEEP(0.15) AS _delay FROM products WHERE id = ?',
    [id]
  );
  const row = rows[0];
  return row
    ? { id: row.id, name: row.name, price: row.price, description: row.description }
    : { id: Number(id), name: 'not-found' };
}

function respond(statusCode, bodyObj) {
  return {
    statusCode,
    statusDescription: statusCode === 200 ? '200 OK' : statusCode === 404 ? '404 Not Found' : '500 Internal Server Error',
    isBase64Encoded: false,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(bodyObj, null, 2),
  };
}

exports.handler = async (event) => {
  const t0 = Date.now();
  const path = (event.path || '/').replace(/\/+$/, '') || '/';

  if (path === '/health') {
    return respond(200, { status: 'ok', container_id: CONTAINER_ID });
  }

  const pool = getDbPool();

  // --- Endpoint SIN cache: siempre golpea RDS directo, nunca toca Redis ---
  const dbOnlyMatch = path.match(/^\/db\/item\/(\d+)$/);
  if (dbOnlyMatch) {
    const id = dbOnlyMatch[1];
    try {
      await ensureSeeded(pool);
      const tDb0 = Date.now();
      const item = await queryProduct(pool, id);
      const dbQueryMs = Date.now() - tDb0;

      return respond(200, {
        item,
        endpoint: '/db/item/{id}',
        source: 'database', // este endpoint SIEMPRE es database - no usa cache
        container_id: CONTAINER_ID,
        db_query_ms: dbQueryMs,
        total_latency_ms: Date.now() - t0,
        timestamp: new Date().toISOString(),
      });
    } catch (err) {
      return respond(500, { error: err.message, container_id: CONTAINER_ID, total_latency_ms: Date.now() - t0 });
    }
  }

  // --- Endpoint CON cache: cache-aside normal (Redis primero, RDS si hay miss) ---
  const match = path.match(/^\/item\/(\d+)$/);
  if (match) {
    const id = match[1];
    const redis = getRedis();
    const cacheKey = `item:${id}`;

    try {
      let source = 'cache';
      let item;
      let cacheLookupMs = 0;
      let dbQueryMs = 0;

      const tCache0 = Date.now();
      let raw = null;
      try {
        if (redis.status === 'wait') await redis.connect();
        raw = await redis.get(cacheKey);
      } catch (e) {
        raw = null;
      }
      cacheLookupMs = Date.now() - tCache0;

      if (raw) {
        item = JSON.parse(raw);
      } else {
        source = 'database';
        await ensureSeeded(pool);
        const tDb0 = Date.now();
        item = await queryProduct(pool, id);
        dbQueryMs = Date.now() - tDb0;
        try {
          await redis.set(cacheKey, JSON.stringify(item), 'EX', CACHE_TTL);
        } catch (e) {
          /* si no se pudo cachear, no es fatal */
        }
      }

      return respond(200, {
        item,
        endpoint: '/item/{id}',
        source, // "cache" | "database"
        container_id: CONTAINER_ID,
        cache_lookup_ms: cacheLookupMs,
        db_query_ms: dbQueryMs,
        total_latency_ms: Date.now() - t0,
        cache_ttl_seconds: CACHE_TTL,
        timestamp: new Date().toISOString(),
      });
    } catch (err) {
      return respond(500, { error: err.message, container_id: CONTAINER_ID, total_latency_ms: Date.now() - t0 });
    }
  }

  return respond(404, { error: 'not found', path });
};
