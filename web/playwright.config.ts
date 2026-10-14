import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests',workers:1,timeout:60000,expect:{timeout:20000},
 outputDir:'../data/qa/playwright-artifacts',reporter:[['list'],['junit',{outputFile:'../data/qa/ui-results.xml'}]],
 use:{baseURL:process.env.APP_TEST_URL||'http://127.0.0.1:8001',channel:'msedge',viewport:{width:1536,height:1024},
 screenshot:'only-on-failure',trace:'retain-on-failure'}});
