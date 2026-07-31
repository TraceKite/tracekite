import express from 'express';

const app = express();

app.get('/users/:id', (req, res) => {
  res.send(getUser(req.params.id));
});

function getUser(id: string) {
  return { id };
}
