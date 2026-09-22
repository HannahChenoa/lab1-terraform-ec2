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

function respond(statusCode, bodyObj) {
  return {
    statusCode,
    statusDescription: statusCode === 200 ? '200 OK' : '500 Internal Server Error',
    isBase64Encoded: false,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(bodyObj, null, 2),
  };
}

exports.handler = async (event) => {
  const t0 = Date.now();
  const path = (event.path || '/').replace(/\/+$/, '') || '/';

  if (path === '/health') {
    return respond(200, { status: 'ok', container_id: CONTAINER_ID });
  }

  const match = path.match(/^\/item\/(\d+)$/);
  const id = match ? match[1] : '1';
  const qs = event.queryStringParameters || {};
  const forceFresh = qs.fresh === '1'; // ?fresh=1 -> ignora y borra el cache (simula "cache no cargado")

  const redis = getRedis();
  const pool = getDbPool();
  const cacheKey = `item:${id}`;

  try {
    if (forceFresh) {
      try {
        if (redis.status === 'wait') await redis.connect();
        await redis.del(cacheKey);
      } catch (e) {
        /* si Redis falla igual seguimos por la BD */
      }
    }

    let source = 'cache';
    let item;
    let cacheLookupMs = 0;
    let dbQueryMs = 0;

    const tCache0 = Date.now();
    let raw = null;
    if (!forceFresh) {
      try {
        if (redis.status === 'wait') await redis.connect();
        raw = await redis.get(cacheKey);
      } catch (e) {
        raw = null;
      }
    }
    cacheLookupMs = Date.now() - tCache0;

    if (raw) {
      item = JSON.parse(raw);
    } else {
      source = 'database';
      const tDb0 = Date.now();
      await ensureSeeded(pool);

      // Consulta "pesada" a propósito (SLEEP simula un query costoso / join real)
      // para que se note la diferencia real contra servir desde Redis.
      const [rows] = await pool.query(
        'SELECT id, name, price, description, SLEEP(0.15) AS _delay FROM products WHERE id = ?',
        [id]
      );

      dbQueryMs = Date.now() - tDb0;

      const row = rows[0];
      item = row
        ? { id: row.id, name: row.name, price: row.price, description: row.description }
        : { id: Number(id), name: 'not-found' };

      try {
        await redis.set(cacheKey, JSON.stringify(item), 'EX', CACHE_TTL);
      } catch (e) {
        /* si no se pudo cachear, no es fatal */
      }
    }

    const totalLatencyMs = Date.now() - t0;

    return respond(200, {
      item,
      source, // "cache" | "database"
      container_id: CONTAINER_ID,
      cache_lookup_ms: cacheLookupMs,
      db_query_ms: dbQueryMs,
      total_latency_ms: totalLatencyMs,
      cache_ttl_seconds: CACHE_TTL,
      timestamp: new Date().toISOString(),
    });
  } catch (err) {
    return respond(500, {
      error: err.message,
      container_id: CONTAINER_ID,
      total_latency_ms: Date.now() - t0,
    });
  }
};
