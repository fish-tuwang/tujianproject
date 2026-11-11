const { createListPage } = require('../../lib/page-factory');
const definition = createListPage('pokemon');
if (typeof Page === 'function') Page(definition);
module.exports = definition;
